"""User-paced, persisted study progress. Never initiates outreach."""
import re
from pastor_ray.scripture import books, passages

TOPICS = {
    'prayer': ['Matthew 6:5-13', 'Philippians 4:4-9', 'Psalms 23', 'James 1:2-8'],
    'forgiveness': ['Ephesians 4:25-32', 'Matthew 18:21-35', 'Romans 12:17-21'],
    'faith': ['Ephesians 2:1-10', 'John 3:1-18', 'James 2:14-26', 'Hebrews 11:1-16'],
}

def intent(text):
    if re.fullmatch(r'(?:please )?(?:continue|resume) (?:my|our|the) (?:study|discipleship|plan)[.!?]?', text, re.I):
        return 'current'
    m = re.fullmatch(r"(?:let's study|start (?:a |my )?(?:study|discipleship)(?: plan)? (?:on|about)|start a plan on) (.{1,100}?)[.!?]?", text, re.I)
    return 'start '+m[1] if m else None

def command(store, uid, args):
    parts = args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else 'current'
    value = parts[1].strip() if len(parts)>1 else ''
    plan = store.plan(uid)
    if action == 'start':
        if plan and plan['status'] != 'complete':
            return 'You already have a plan. Use !ray plan current, or !ray plan end before starting another.'
        book = next((b for b in books() if b.lower()==value.lower()), None)
        if book:
            steps = []
            for i, chapter in enumerate(books()[book],1):
                for start in range(1,len(chapter['verses'])+1,15):
                    steps.append(f'{book} {i}:{start}-{min(start+14,len(chapter["verses"]))}')
        elif value.lower() in TOPICS:
            steps = TOPICS[value.lower()]
        else:
            return 'Start with any Bible book, or prayer, forgiveness, or faith: !ray plan start John. You can discuss any other goal with me in conversation.'
        plan = {'topic':value,'steps':steps,'step':0,'status':'active','pace':'your own pace','reflections':[]}
    elif not plan:
        return 'No plan yet. Try !ray plan start John, prayer, forgiveness, or faith.'
    elif action in ('next','complete'):
        if plan['status'] != 'active':
            return 'Your plan is paused or complete. Use !ray plan resume for a paused plan.'
        plan['step'] += 1
        if plan['step'] >= len(plan['steps']):
            plan['status'] = 'complete'
    elif action == 'pause':
        plan['status'] = 'paused'
    elif action == 'resume' and plan['step'] < len(plan['steps']):
        plan['status'] = 'active'
    elif action == 'end':
        plan['status'] = 'complete'
    elif action == 'pace' and value:
        plan['pace'] = value[:200]
    elif action == 'reflect' and value:
        plan['reflections'].append({'step':plan['step']+1,'text':value[:2000]})
        store.archive(uid,'user','Study reflection: '+value)
    elif action not in ('current','status'):
        return 'Plan controls: start <book/topic>, current, next, pause, resume, pace <preference>, reflect <thought>, end.'
    store.save_plan(uid,plan)
    if plan['status']=='complete':
        return 'Your plan is complete. Your conversations and reflections remain in your private memory. Use !ray plan start <book/topic> when ready.'
    ref = plan['steps'][plan['step']]
    return (f"**Your {plan['topic']} study** — {plan['status']}, step {plan['step']+1}/{len(plan['steps'])}; {plan['pace']}.\n\n"
            +'\n'.join(passages(ref))
            +'\n\nWhat stands out, what does it mean in context, and how might you live it out? We can explore this as deeply as you want. Use !ray plan next only when ready; !ray plan reflect <thought> saves your reflection.')

def context(plan):
    if not plan:
        return None
    return {**{k:v for k,v in plan.items() if k not in ('steps','reflections')},
            'current_reading':plan['steps'][min(plan['step'],len(plan['steps'])-1)],
            'recent_reflections':plan['reflections'][-3:]}
