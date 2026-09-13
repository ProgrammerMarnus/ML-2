# Reproducible research workflow

The engine records data hashes and experiment metadata. DVC adds content-addressed
storage and a replayable dependency graph around those artifacts; it does not
replace the experiment registry, locked-test protocol, or promotion gates.

1. Install the optional tooling: `pip install -e '.[reproducibility]'`.
2. Initialize the repository once with `dvc init` and configure a team-approved
   remote. Do not store credentials in this repository.
3. Add an immutable raw provider snapshot with `dvc add data/raw_snapshots/<hash>.csv`.
   Commit only the generated `.dvc` metadata, then push cache data to the approved
   remote.
4. Run `dvc repro research-baseline` for the offline baseline. Its output is
   content-addressed and tied to its configuration and code dependencies.

For actual market research, every run must still record the provider, retrieval
time, raw snapshot hash, `exchange_calendars` version, model revision, and output
manifest. A DVC cache hit is reproducibility evidence, not evidence of tradability.
