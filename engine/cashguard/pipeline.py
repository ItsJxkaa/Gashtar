import json
import time
from pathlib import Path

from .inference import LocalModel
from .departure import analyze_departures
from .workflow import observe_workflow, context_hint
from .identity import analyze_identity
from .schemas import Scan, Verification, Violation, Evidence
from .video import metadata, sample, uniform, windows

CATALOGUE = json.loads(Path(__file__).with_name("rules.json").read_text(encoding="utf-8"))
RULES = {r["id"]: r for r in CATALOGUE["rules"]}


def merge_candidates(candidates, seconds=6):
    kept = []
    for candidate in sorted(candidates, key=lambda c: c.confidence, reverse=True):
        if not any(c.rule_id == candidate.rule_id and abs(c.timecode_sec - candidate.timecode_sec) <= seconds for c in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda c: c.timecode_sec)


def analyze(path, settings, progress=lambda stage, pct: None, model=None):
    started = time.monotonic()
    deadline = started + settings.deadline_sec - 8
    info = metadata(path)
    duration = info["duration_sec"]
    if duration > settings.max_duration_sec:
        raise ValueError(f"Video duration exceeds {settings.max_duration_sec:g} seconds")
    model = model or LocalModel(settings)
    context = None
    if settings.workflow_context:
        progress("workflow", 3)
        context = observe_workflow(path, duration, settings, model, deadline)
    timeline = list(windows(duration, settings.window_sec, settings.stride_sec))
    # A long transaction can cross window boundaries. Its beginning and end
    # must be available to retrieval as well as independent verification.
    if len(timeline) > 1:
        timeline.insert(0, (0.0, duration - 0.05))
    candidates = []
    # Retrieval uses concise rules; the independent verifier applies the complete
    # visual tests and exceptions. Rejecting uncertainty during retrieval hides
    # candidates before their surrounding context can be examined.
    legacy_rules = [r for r in CATALOGUE["rules"] if r.get("pipeline_stage") not in {"departure","identity"}]
    legacy_ids = {r["id"] for r in legacy_rules}
    rule_prompt = json.dumps([{k: r[k] for k in ("id", "type", "summary", "absence")}
                              for r in legacy_rules], ensure_ascii=False)
    progress("scanning", 5)
    for i, (start, end) in enumerate(timeline):
        count = settings.overview_frames if end - start > settings.window_sec else settings.coarse_frames
        frames = sample(path, uniform(start, end, count))
        prompt = f"""Inspect this chronological window of a {duration:.2f}-second video.
Window: {start:.2f} through {end:.2f} seconds. Retrieve all plausible visible candidate
events under this catalogue: {rule_prompt}
Return an object with candidates (empty list when none). Each candidate has rule_id,
timecode_sec (absolute video seconds of the visible act, or completion for omission),
observation, confidence (0..1, a heuristic score), complete_sequence (boolean).
Track where money and personal containers move, who remains at the counter, cash
transfers and any visible departure. A proposal is not a confirmed violation: include
visible but uncertain events for the next review stage rather than resolving all
uncertainty as an empty list. Do not manufacture a candidate. Do not quote law.
"""
        answer = model.ask(prompt + context_hint(context, start, end), frames, Scan, deadline)
        for c in answer.candidates:
            if c.rule_id not in legacy_ids:
                raise ValueError("Model returned an unknown rule ID")
            if not start - 0.1 <= c.timecode_sec <= end + 0.1:
                raise ValueError("Model returned a timestamp outside its window")
            if c.confidence >= 0.35:
                candidates.append(c)
        progress("scanning", int(5 + 50 * (i + 1) / len(timeline)))

    candidates = merge_candidates(candidates)
    if len(candidates) > settings.max_candidates:
        # Never silently truncate events or claim an incomplete negative result.
        raise ValueError("Too many candidate events for the configured review budget")
    violations, audit = [], []
    for i, c in enumerate(candidates):
        rule = RULES[c.rule_id]
        # Dense local frames establish the act; full-clip context distinguishes
        # a departure after completion from leaving an unfinished transaction.
        lo, hi = max(0, c.timecode_sec - 4), min(duration - 0.05, c.timecode_sec + 4)
        times = uniform(lo, hi, 9)
        times += uniform(0, duration - 0.05, settings.overview_frames)
        frames = sample(path, times)
        prompt = f"""Independently decide whether the frames support a visible indicator of a POSSIBLE violation.
Weigh both supporting evidence and counterevidence. This is a referral for human review,
not a legal finding. Do not assume either that the proposal is true or that it is false.
Rule: {json.dumps(rule, ensure_ascii=False)}
Proposed time ONLY: {c.timecode_sec:.2f}. Do not assume the proposal is true.
Examine chronological frames. Return confirmed, rule_id, timecode_sec, observation,
counterevidence, confidence (0..1), complete_sequence. Use Russian for descriptions.
The timestamp must be a supplied frame timestamp. Reject if the visual test is not met,
if the supposed act is only inferred, or if visible evidence supports an applicable exception.
Do not invent an off-camera innocent explanation merely because it is theoretically possible.
Follow every uncertainty restriction and exception explicitly listed in this rule.
For omission, require the entire relevant transaction to be visible.
"""
        prompt += '\nThe retrieval stage proposed the following observable action. Treat it as a hypothesis to CHECK against pixels, not as truth: ' + c.observation
        v = model.ask(prompt + context_hint(context, 0, duration), frames, Verification, deadline)
        if v.rule_id != c.rule_id:
            raise ValueError("Verifier changed the rule ID")
        if not frames[0].timestamp - .1 <= v.timecode_sec <= frames[-1].timestamp + .1:
            raise ValueError("Verifier timestamp outside observed frames")
        audit.append({"rule_id": v.rule_id, "confirmed": v.confirmed, "confidence": v.confidence,
                      "complete_sequence": v.complete_sequence})
        if v.confirmed and v.confidence >= settings.confirmation_threshold and (not rule["absence"] or v.complete_sequence):
            index = min(range(len(frames)), key=lambda j: abs(frames[j].timestamp - v.timecode_sec))
            if abs(frames[index].timestamp - v.timecode_sec) > 0.6:
                raise ValueError("Verifier did not select a supplied frame timestamp")
            chosen = sorted({max(0, index - 1), index, min(len(frames) - 1, index + 1)})
            timestamp = frames[index].timestamp
            evidence = [Evidence(timestamp_sec=frames[j].timestamp, image_base64=frames[j].jpeg()) for j in chosen]
            reference = {**CATALOGUE["source"], "id": rule["id"], "section": rule["section"], "summary": rule["summary"]}
            description = f"{v.observation} Возможный признак несоблюдения правила ({rule['section']}). Требуется проверка человеком."
            violations.append(Violation(type=rule["type"], timecode_sec=timestamp, description=description,
                                        evidence_frames=evidence, rule=reference, confidence=v.confidence).model_dump())
        progress("verifying", int(55 + 40 * (i + 1) / max(1, len(candidates))))
    identity_audit = {"enabled": settings.identity_checks}
    if settings.identity_checks:
        progress("identity",95)
        identity_events,details=analyze_identity(path,duration,settings,model,deadline,RULES['customer_cash_no_visible_id'])
        violations.extend(identity_events)
        identity_audit.update(details)
    departure_audit = {"enabled": settings.departure_checks}
    if settings.departure_checks:
        progress("departures", 96)
        departure_events, details = analyze_departures(path, duration, settings, model, deadline, RULES, progress, context_hint(context, 0, duration))
        departure_events = [e for e in departure_events if e['rule']['id'] != 'departure_key_in_lock' or not any(v['rule']['id']=='cash_storage_key_unattended' and abs(v['timecode_sec']-e['timecode_sec'])<=6 for v in violations)]
        violations.extend(departure_events)
        departure_audit.update(details)
    if time.monotonic() > deadline:
        raise TimeoutError("Video analysis deadline exceeded")
    # A fixed deployment policy; uploaded names, hashes and labels are never used.
    suppressed = sum(v["rule"]["id"] in settings.disabled_rule_ids for v in violations)
    violations = [v for v in violations if v["rule"]["id"] not in settings.disabled_rule_ids]
    violations.sort(key=lambda v: v["timecode_sec"])
    progress("complete", 100)
    return {"verdict": "violation" if violations else "no_violation", "violations": violations,
            "analysis": {"pipeline_version": "2026-10-18.28", "duration_sec": duration, "elapsed_sec": round(time.monotonic() - started, 2),
                         "model": settings.model_name, "rules_version": CATALOGUE["version"],
                         "windows_reviewed": len(timeline), "candidates_reviewed": len(audit),
                         "verification_counts": {"confirmed": sum(v["confirmed"] for v in audit),
                                                 "rejected": sum(not v["confirmed"] for v in audit),
                                                 "complete_sequence": sum(v["complete_sequence"] for v in audit)},
                         "model_calls": getattr(model, "calls", []),
                         "departure_checks": departure_audit,
                         "identity_checks": identity_audit,
                         "screen_recheck": settings.screen_recheck,
                         "storage_detail": settings.storage_detail,
                         "workflow_context": {"enabled": settings.workflow_context, "phases": [p.kind for p in context.phases] if context else []},
                         "complete": True, "confidence_is_calibrated": False,
                         "disabled_rule_ids": list(settings.disabled_rule_ids),
                         "suppressed_unvalidated_events": suppressed,
                         "coverage_notice": "Категория «Пересчет принимаемых денег без клиента» отключена из-за ложных срабатываний в испытаниях." if "count_without_customer" in settings.disabled_rule_ids else "",
                         "notice": "Результат основан на выборке кадров. Отсутствие признаков не гарантирует соблюдение всех правил."}}

