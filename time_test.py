import time
from aira.orchestrator import run_audit
import logging
logging.basicConfig(level=logging.INFO)

t0 = time.time()
print("starting audit...")
report = run_audit("https://www.nike.com/", include_evidence_model=False)
print(f"finished in {time.time()-t0}s")
