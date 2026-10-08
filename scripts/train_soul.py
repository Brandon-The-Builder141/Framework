"""
Train the soul model on curated instruction-response pairs.
Uses Hugging Face + LoRA. Requires: transformers, peft, datasets, torch.

Usage:
  python scripts/train_soul.py <curated.jsonl> [--base MODEL] [--output DIR] [--epochs N] [--dry-run]
  python scripts/train_soul.py data/soul_training/curated.jsonl --dry-run
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from config.settings import SOUL_TRAINING_DIR, SOUL_BASE_MODEL


def dry_run(input_path: Path) -> tuple[int, bool]:
    """Validate JSONL, return (count, ok)."""
    if not input_path.exists():
        return 0, False
    lines = [ln.strip() for ln in input_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    count = 0
    for ln in lines:
        try:
            obj = json.loads(ln)
            if isinstance(obj, dict) and "instruction" in obj and "response" in obj:
                count += 1
        except json.JSONDecodeError:
            pass
    return count, count > 0


def train(input_path: Path, base_model: str, output_dir: Path, epochs: int = 2) -> Path:
    """Run LoRA fine-tuning. Returns output dir."""
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer, DataCollatorForLanguageModeling
        from peft import LoraConfig, get_peft_model, TaskType
        from datasets import Dataset
    except ImportError as e:
        print(f"Missing deps for training. pip install transformers peft datasets torch accelerate: {e}")
        raise SystemExit(1)

    lines = [ln.strip() for ln in input_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    data = []
    for ln in lines:
        try:
            obj = json.loads(ln)
            if isinstance(obj, dict) and "instruction" in obj and "response" in obj:
                inst = obj["instruction"]
                resp = obj["response"]
                data.append({"text": f"### Instruction:\n{inst}\n### Response:\n{resp}\n"})
        except json.JSONDecodeError:
            pass
    if not data:
        raise ValueError("No valid pairs in curated.jsonl")
    dataset = Dataset.from_list(data)

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    print(f"Loading base model: {base_model} (dtype={dtype})")
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    # TinyLlama has no pad token — must set before any padding operations
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        trust_remote_code=True,
        torch_dtype=dtype,
    )
    model.config.pad_token_id = tokenizer.pad_token_id

    if "TinyLlama" in base_model or "smol" in base_model.lower():
        lora = LoraConfig(r=8, lora_alpha=16, task_type=TaskType.CAUSAL_LM, target_modules=["q_proj", "v_proj"])
    else:
        lora = LoraConfig(r=8, lora_alpha=16, task_type=TaskType.CAUSAL_LM)
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    def tokenize(examples):
        out = tokenizer(examples["text"], truncation=True, max_length=512)
        return out

    tokenized = dataset.map(tokenize, batched=True, remove_columns=dataset.column_names)

    # DataCollatorForLanguageModeling with mlm=False sets labels=input_ids automatically,
    # which is required for causal LM loss to compute correctly in Trainer.
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    fp16 = torch.cuda.is_available()
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=2,
        save_strategy="no",
        logging_steps=1,
        fp16=fp16,
        report_to="none",
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=collator,
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    return output_dir


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python scripts/train_soul.py <curated.jsonl> [--base MODEL] [--output DIR] [--epochs N] [--dry-run]")
        sys.exit(1)
    inp = Path(args[0])
    base = SOUL_BASE_MODEL
    out_dir = SOUL_TRAINING_DIR / "soul_model"
    epochs = 2
    dry = False
    i = 1
    while i < len(args):
        if args[i] == "--base" and i + 1 < len(args):
            base = args[i + 1]
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            out_dir = Path(args[i + 1])
            i += 2
        elif args[i] == "--epochs" and i + 1 < len(args):
            epochs = int(args[i + 1])
            i += 2
        elif args[i] == "--dry-run":
            dry = True
            i += 1
        else:
            i += 1

    if dry:
        count, ok = dry_run(inp)
        if ok:
            print(f"Dry-run OK: {count} pairs ready for training. Run without --dry-run to train.")
        else:
            print("Dry-run FAIL: no valid pairs or file missing.")
        sys.exit(0 if ok else 1)

    out_dir.mkdir(parents=True, exist_ok=True)
    train(inp, base, out_dir, epochs)
    print(f"Training complete. Model saved to: {out_dir}")


if __name__ == "__main__":
    main()
