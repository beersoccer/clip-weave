# Durable Job Ledger Design

**Status:** approved design; implementation has not started.

## Goal

Make a repeat `gen-video` invocation resume already-submitted video tasks instead
of submitting the same prompt again and consuming more model quota.  The change
uses the existing `manifest.json` path and `generate_clips()` entry point.

## Scope

The MVP covers atomic local state persistence, resume, and duplicate-submit
prevention for one storyboard/provider output directory.  It does not add a new
CLI command, a database, cross-machine coordination, provider capability
discovery, provider-side idempotency headers, automatic retry/backoff, media QC,
or hashes.

## Current problem

`generate_clips()` keeps every `ClipResult` only in memory and writes
`manifest.json` once, after polling and downloads finish.  A process stop after
`VideoModel.submit()` therefore loses the provider task ID.  Rerunning the same
storyboard submits the task again.

## Data model

`renders/ai-clips/<provider>/manifest.json` becomes a versioned, durable record.
It retains the existing top-level storyboard, provider, model, resolution, and
ratio fields and adds `schema_version: 2`.  Each clip record adds:

- `request_fingerprint`: SHA-256 of canonical JSON containing provider, model,
  frame index, prompt, duration, ratio, resolution, negative prompt, seed,
  audio flag, watermark flag, and reference value.
- `state`: one of `submitting`, `running`, `download_pending`, `succeeded`, or
  `failed`.
- Existing task ID, provider result URL, local video path, error, elapsed time,
  and request-derived metadata.

The fingerprint is a local semantic identity, not a provider API idempotency
key.  It is recomputed before every invocation.  An existing record is reusable
only when its fingerprint matches exactly.

The manifest may contain historical records for an earlier fingerprint of the
same frame.  The active invocation selects by frame index plus fingerprint, so
an intentional prompt or parameter change creates a fresh job without erasing
the previous provider task record.

## Atomic persistence

All writes go through one private helper:

1. Serialize the complete manifest to a uniquely named temporary file in the
   manifest directory.
2. Flush and `fsync` the temporary file.
3. Replace `manifest.json` with `os.replace()`.

The helper runs before a provider submit and after every durable transition.  A
write failure aborts that job before any provider call.  There is no new storage
dependency.

## State machine

| State | Meaning | Next action on a repeat invocation |
| --- | --- | --- |
| `submitting` | The request fingerprint was persisted before `submit()`, but no provider task ID was persisted. | Stop this job and report its recorded error; never auto-submit it again. |
| `running` | A provider task ID was persisted. | Poll the existing task ID only. |
| `download_pending` | Provider returned a successful video URL, but local output is not confirmed. | Download the existing provider result only. |
| `succeeded` | The destination file was written and its path persisted. | Reuse it only when the file still exists. |
| `failed` | The provider reported a terminal failure. | Return the recorded failure; do not retry automatically. |

Transitions are:

```text
new job -> submitting -> running -> download_pending -> succeeded
                         |             |
                         +-> failed    +-> download_pending (download error)
```

Before the remote call, `submitting` is written atomically.  On a successful
submit, the returned task ID and `running` state are written atomically before
polling.  If submit raises or the process ends in this interval, the record stays
`submitting`; that ambiguity is intentionally not retried because avoiding an
extra model task is more important than guessing whether the provider accepted
the request.

Polling records `download_pending` as soon as the provider reports success and
its result URL is available.  A download failure leaves that state intact for a
later download-only recovery.  The downloaded file is written to a temporary
path and atomically renamed before `succeeded` is persisted.

`max_wait` and a transient polling error are observation failures, not provider
terminal failures: the job remains `running`, records the last error if any, and
can be resumed later.  Only an explicit provider failure becomes `failed`.

## Resume algorithm

For each selected storyboard frame, build the same effective `VideoRequest` and
fingerprint that a new submission would use, then load its matching record:

1. Matching `succeeded` with an existing file: return it without provider I/O.
2. Matching `running`: add its persisted task ID to the poll set.
3. Matching `download_pending`: add it to the download set.
4. Matching `submitting` or `failed`: return its recorded non-retriable result.
5. No matching record: append and atomically persist `submitting`, then submit.

The normal execution remains batch-shaped: new jobs are submitted first,
persisted task IDs are polled together, and completed jobs are downloaded.  The
resume path simply feeds existing jobs into the later phases rather than calling
`submit()` again.

## Compatibility

An older manifest with no `schema_version` is treated as a legacy final summary.
It is not used to resume an active task because it cannot prove a durable task
ID/fingerprint pairing.  A new invocation writes the version-2 format.  The
legacy file is first read defensively so malformed JSON produces an actionable
error rather than being overwritten.

## Tests

Add offline tests in `tests/test_video_pipeline.py` using `FakeModel`:

1. The manifest exists with a `running` task ID immediately after a later submit
   failure interrupts the batch.
2. A second identical invocation polls a persisted task ID and never calls
   `submit()` for it.
3. A successful existing file is reused without model calls.
4. Provider success followed by a download error resumes as download-only.
5. Timeout or transient poll error remains resumable rather than becoming
   `failed`.
6. A persisted `submitting` record never causes an automatic resubmit.
7. Changing a prompt or request parameter produces a different fingerprint and
   submits exactly one new task.
8. Atomic-write failure before submit prevents the model from receiving a
   request.

Run the focused pipeline tests, then the full `uv run pytest` suite and
`git diff --check`.

## References

- AWS Builders' Library, [Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)
- Stripe, [Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- Temporal, [Activities](https://docs.temporal.io/encyclopedia/activities)
- Google AIP-151, [Long-running operations](https://google.aip.dev/151)
