Trained 2026-09-12T23:39 on 5,486 rows with 7 fraud labels and a 22-second test window,
because `make train` ran right after the host woke and the generator had correctly skipped
ahead instead of backfilling. It reported pr_auc 1.0 and suggested a threshold of 0.05, and
it served live decisions until it was noticed.

Kept, not deleted, because it is the reason `training/train.py` now has `check_trainable()`
(MIN_POSITIVES and MIN_TEST_WINDOW_MINUTES, bypassable only with --force).
