"""Load test for the frugal layer.

Default profile measures the layer itself: a pool of popular questions is asked repeatedly, so
after warm-up most requests are cache hits (embedding + lookup only), mixed with stats reads.
Run the server with FRUGAL_FAKE_LLM=1 to keep cache misses at $0 and off the free-tier quota.

  FRUGAL_FAKE_LLM=1 FRUGAL_MAX_DAILY_CALLS=100000 uvicorn frugal.api.main:app --port 8000
  locust -f loadtest/locustfile.py --host http://localhost:8000 -u 50 -r 25 -t 60s --headless \
         --csv results/loadtest/local
"""

import os
import random

from locust import HttpUser, between, task

HEADERS = {"authorization": f"Bearer {os.environ['FRUGAL_API_TOKEN']}"} if os.environ.get("FRUGAL_API_TOKEN") else {}
POPULAR = [
    ("swiggy", "How long do refunds take after I cancel an order?"),
    ("swiggy", "Does Swiggy One give free delivery on Instamart?"),
    ("github", "What is the minimum interval for a scheduled workflow?"),
    ("github", "How many jobs can a matrix generate?"),
    ("tax", "What is the standard deduction under the new regime?"),
    ("tax", "Who can opt for the GST composition scheme?"),
    ("legal", "Is a non-compete clause enforceable in India?"),
    ("legal", "What is a void agreement under the Contract Act?"),
]


class FrugalUser(HttpUser):
    wait_time = between(0.05, 0.2)

    @task(8)
    def popular_question(self):
        domain, q = random.choice(POPULAR)
        self.client.post("/v1/answer", json={"question": q, "domain": domain}, headers=HEADERS, name="/v1/answer")

    @task(1)
    def stats(self):
        self.client.get("/v1/stats", name="/v1/stats")

    @task(1)
    def health(self):
        self.client.get("/healthz")
