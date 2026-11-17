# Save transaction regression and fix

Author: matymeatboy.

The existing runtime validates buffers and reports file write errors, but writes
directly into the committed slot. A `WRITE` opens its old payload with `wb` before
checking `fwrite`, flush, truncation and close results. Also, a later callback
failure leaves earlier writes committed, and `reCreate` can remove the old slot
before that failure. Returning an error does not restore the player's progress.

The regression was reproduced with the real `cellSaveData.c`, guest callbacks
and synthetic files: both a normal overwrite followed by a failing callback and
the same sequence with `reCreate` changed the previous payload despite reporting
failure. A short-write injection exercises the actual file producer as well.

`src/tj_savedata_transaction.cpp` and the independent
`patches/ps3recomp/tj-savedata-atomic.patch` make the whole directory transactional:

- Every callback operates on an independent copy, including `PARAM.SFO`, file
  deletion, offset writes and `reCreate`.
- A new slot stays absent in the candidate until the runtime creates it, so
  `isNewData` retains its original meaning.
- Only a successful complete operation publishes the candidate. Existing files
  are flushed first; errors discard the candidate and retain the old slot.
- A per-slot OS lock rejects concurrent operations. Links and Windows reparse
  points are rejected before copying, deleting or publishing directories.
- A single prior generation is retained outside manual slots, at
  `<savedata-root>/.savedata-recovery/<slot>/previous`.
- Explicit FixedDelete uses the same slot lock and clears its prior generation
  before deletion. A later load cannot resurrect a deliberately deleted save.
- List/Fixed enumeration recovers interrupted slots under their locks before
  offering the directory list to game callbacks.
- If a process stops between moving the original aside and publishing its
  replacement, the next save **or load** restores that committed generation
  before callbacks see the slot. An unfinished candidate is discarded.

Windows cannot replace an existing nonempty directory with one rename. The
publication uses two directory renames, with recovery for the intermediate
state. Tests simulate a process interruption at that exact point. This is not a
claim of guaranteed recovery from power loss, filesystem damage or incompatible
save formats. The code treats the game's successful callbacks as its validation
contract; it cannot independently validate opaque game payloads.

The implementation has no trophy, achievement, SDK or game-content dependency.
To integrate, compile the C++17 helper into the game and define
`TJ_SAVEDATA_TRANSACTION=1` for the runtime source. Apply the separate patch after
the locked runtime's existing compatibility patches. It also applies when the
optional trophy patch is absent. The guest-I/O test target must link the helper
and use the same definition.

Verification:

```
python -m pytest tests/test_tj_savedata_transaction.py -q
```

The tests compile and execute the actual runtime and existing guest-I/O harness,
with additional late callback failures, short writes and failed `reCreate`.
It also calls the actual FixedDelete guest handler after two saves and then
AutoLoad, checking that the slot stays absent and is reported as new. A separate
run interrupts directory publication before FixedDelete enumeration to verify
that listing sees the recovered slot before deleting it.
They retain its normal reads, writes, offset/truncation checks and callback
userdata rebinding. Separate helper tests cover failed directory publication,
metadata/delete rollback, concurrent operation rejection, interrupted-process
recovery, new-slot semantics and a real Windows directory junction. All test
data lives in temporary directories; no player saves are opened or modified.

The original upstream new-save callback error mapping remains intact: that
separate fix is necessary for first-boot progression. This change does not
alter game unlock conditions and does not establish gameplay or real-game
cross-session verification.
