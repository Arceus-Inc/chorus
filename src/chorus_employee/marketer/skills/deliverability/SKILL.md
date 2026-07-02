---
name: deliverability
description: How to get email to the inbox — sender reputation, list hygiene, warmup, and the self-limiting ceiling on send volume. The craft behind email.send.
when_to_use: Read before staging any email.send go-live, and whenever a task involves sending to a list rather than a single recipient. It shapes what you send and how much, not just what it says.
---

# Deliverability

A brilliant email that lands in spam did not happen. Deliverability is the discipline that keeps
send *reaching* people — and it is mostly about restraint, reputation, and list quality, not copy.

## The one rule

**Send less, to people who want it, from a warm domain.** Every deliverability failure traces back
to violating one of those three. Volume, consent, and reputation — protect them in that order.

## Sender reputation

- **Warm up new domains/IPs.** A cold domain that suddenly sends thousands of emails looks exactly
  like a spammer to every inbox provider. Ramp volume over days/weeks; start with your most engaged
  recipients so early opens build reputation.
- **Authenticate** — SPF, DKIM, DMARC aligned. Unauthenticated mail is throttled or junked by
  default. (Operationally this is a domain-setup precondition, not something you set per-send.)
- **A single spam trap or spike in complaints can tank a domain for weeks.** Reputation is slow to
  build and fast to lose — treat it as the scarce asset it is.

## List hygiene

- **Only send to people who asked.** Consent is the strongest deliverability signal there is.
- **Remove hard bounces immediately** and suppress addresses that haven't engaged in a long window —
  sending to dead addresses signals a bought/stale list.
- **Honor unsubscribes instantly and make them one click.** A "mark as spam" is far more damaging
  than an unsubscribe; a friction-free opt-out prevents it.

## The self-limiting ceiling

Deliverability *caps your reach on purpose*: past a certain volume/frequency, each additional send
lowers engagement, which lowers reputation, which lowers inbox placement — so more sending yields
*less* delivered mail. Respect the ceiling:

- Prefer a smaller, engaged segment over a full-list blast. Segment by engagement, not just by list.
- Cadence discipline: a predictable, modest rhythm beats sporadic large sends.
- If activation is the metric, a 40% open on a tight segment beats a 4% open on everyone.

## Before you stage an email go-live

1. Is this the right *segment*, or a lazy full-list blast?
2. Is the volume within a warm domain's safe rate?
3. One-click unsubscribe present; bounces/complaints suppressed?
4. Would a reasonable recipient say "I asked for this"? If not, do not send.

Deliverability is where the marketer's "confidently wrong" shows up as *over-sending* — the honest
move is almost always to send to fewer people, more relevantly.
