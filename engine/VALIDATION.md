# Departure checks — pipeline 2026-10-18.28

Four user-requested departure checks are implemented: an explicitly unlocked laptop, an open cash safe, exposed banknotes or a positively identified cash bag left at the workstation, and a clearly resolved key left in a cash-storage lock. They are workplace-security review criteria, not independently verified legal or bank-policy findings. They produce the brief's binary referral verdict and explicit checklist provenance, with no invented regulation URL.

## Fresh 40-video comparison (original dataset labels)

| Configuration | TP | FN | FP | TN | Processing failures | Recall | Precision | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Previous selected release v19 | 8 | 13 | 1 | 18 | 0 | 38.1% | 88.9% | 0.533 |
| Selected departure/workflow release, full rerun | 10 | 11 | 3 | 16 | 0 | 47.6% | 76.9% | 0.588 |

Newly detected positive clips: **2**. Previously detected positives lost: **0**. Newly flagged clips labeled normal: **2**. Older-rule prediction changes: **0**.

All 40 unique videos had already been used or evaluated in previous work. This rerun is a development benchmark comparison, not an independent holdout test. Exact duplicates remain grouped. The former development/reserved breakdown is retained in `DEPARTURE_EVALUATION.json` for transparency; the eight previously reserved clips are no longer an unseen test set. Binary organizer labels do not establish whether the model has named the correct event type.

The original accuracy-promotion criterion was increased recall, no decrease in F1, zero processing failures, and every video finishing within 270 seconds. A separately identified feature release may keep equal recall/F1 while adding checks; this does not count as improved accuracy. The selected release must also remove the user-confirmed lock-screen false alarm on clip 23. Threshold remains 0.75. The unreliable older `count_without_customer` category remains disabled. No training or per-video label/filename rules were introduced.

## Implementation and limits

The older rule definitions are retained. If workflow context is enabled, an extra visual pass estimates spatial roles and visible phases using the user's observed normal sequences. Its output is an untrusted hypothesis checked against frames; it cannot itself prove an omission or override an exception. Employee-only counting is normal, customer departure is distinct from employee departure, and nearby equipment checks do not imply leaving. Chair/equipment/lights are context cues, not additional violation categories. A separate full-clip pass proposes cashier departures. A factual second pass examines local before/after frames plus the full-clip overview. It returns departure, continuity, supervision, screen, safe and cash/bag states. Deterministic gates accept only supported states above the fixed heuristic confidence threshold. Unknown, unreadable, off/closed or supervised states cannot create a flag. A glowing screen alone, a closed safe's apparent lock state, and an unidentified bag are insufficient.

Original-resolution safe/desk crops independently inspect storage identity, open/closed door state, a visible inserted key, and exposed banknotes or identified cash bags. Closed storage does not prove locking. The higher-resolution pass may reject earlier model interpretations.

Each accepted departure event contains actual PTS-based before/transition/after JPEG evidence, including the event timestamp itself. This improves reviewability, but does not prove the visual interpretation is correct. Cashier/customer roles, small screens and hidden objects remain difficult. The model observes sampled frames, not every instant.

When enabled, the screen recheck independently locates the laptop display, crops original-resolution pixels, and checks for lock/login indicators versus identifiable desktop/application controls. A password-protected lock screen is safe for this criterion; unclear pixels cannot establish accessibility. The user corrected the earlier warning on clip 23 as a locked screen. This annotation is retained in HUMAN_REVIEW_CORRECTIONS.json and never used as a filename-specific inference exception.

The new checks are implemented and exercised, but per-category accuracy cannot be calculated from the available binary labels. `departure_categories` reports the labels of clips flagged by each category; it is not an event-type confusion matrix. The private offline review contains the locally generated evidence and descriptions for human checking.

## Latency and software checks

Full-pipeline wall time: median **44.36s**, maximum **189.08s**. Positive clips with an accepted event within five seconds of a supplied reference: **6/10**. Time proximity alone does not validate the named event.

All **117 software tests** pass, including unknown-state rejection, supervision, temporal order, cash-bag identity, exact JPEG timestamps, checklist provenance, the real worker boundary, and the legacy call contract when both departure and workflow passes are disabled. Python compilation and JavaScript syntax are checked. These tests use synthetic data/model stubs and do not measure visual accuracy. Live operational checks are recorded separately.

All visual AI inference runs on the user's GPU runtime. Private evidence reviews are saved only on the user's runtime and computer. The source archive contains no recordings, private evidence review, model weights or credentials. The previous release and frozen evaluated source are retained under `reproduction/`.

## Rejected intermediate results

The departure-only v20 run reached 13/21 positive clips with 3/19 false alarms, but its apparent gains depended on unreliable laptop-state interpretations. User review identified clip 23 as a password-protected lock screen. Independent original-resolution inspection rejected all seven laptop warnings (two locked, two off/closed, three unresolved). The workflow-conditioning candidate was stopped after 16 clips: 2 detected positives, 1 false alarm and 2 processing failures, versus 6 detected positives and 1 false alarm for departure-only on the same clips. These intermediate counts are not the selected release result. The full comparison records are in DEPARTURE_EVALUATION.json.

Customer identification and human review

User review identifies two customer cash handovers without identification in X38, with counted cash left on the desk. Employee-only counting or desk handling must not become a third ID event. A cash-on-desk warning alone does not establish detection of the ID omission or unattended departure. The separate customer-ID presentation check is enabled in this release. The full-pipeline X38 regression detected the missing-ID criterion.
The old ID-order rule required both cash and later identification handling; it could miss a transaction where ID never appears. A new full-clip scan retrieves customer cash transfers. An independent review uses the complete sequence and denser handover frames. It rejects employee-only cash work, partial views, unresolved documents, plausible digital ID, and possible earlier service. The result is a visible-workflow referral, not proof that identity was absent from banking systems. No filename, label or clip hash is used by inference.

Label dispute: after reviewing the private evidence, the user asked to retain the missing-ID flags on X19 and X39 and suspects faulty normal labels. All benchmark counts above preserve the original labels. These cases are separately documented as disputed, not silently relabeled or treated as independently adjudicated truth.

An independent role-and-timing check locates customer entry, actual cash transfer, and exit. It rejects transfers involving equipment or storage instead of a customer and cannot substitute a later handover for an earlier candidate. Overlapping customer episodes are deduplicated; separate customers remain separate events. These checks do not establish that every visual interpretation is correct.

A final document countercheck independently crops original-resolution handover frames across each customer episode. Visible or plausible physical/digital ID, an unresolved object, an obscured region, or failed localization blocks an absence alert. This extra check is evaluated in the full pipeline, including its latency.

## Live deployment checks

The measured source was deployed while preserving the model backend and temporary HTTPS URL. A real X38 upload with a randomized filename reproduced the measured ID event count and valid JPEG evidence through the job API. X23 returned no violation through that API. Public HTTPS, authentication, the rule catalogue, and a synthetic non-event upload also passed. See DEPLOYMENT_CHECKS.json. No jury submission was made.
