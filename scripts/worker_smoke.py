"""Send a task through the configured broker and wait for the actual worker."""

from apps.worker.tasks import smoke_task


def main() -> None:
    result = smoke_task.delay("cli-smoke").get(timeout=10)
    expected = {"status": "ok", "service": "documind-worker", "message": "cli-smoke"}
    if result != expected:
        raise SystemExit("Worker returned an unexpected smoke response")
    print("Worker smoke PASS")


if __name__ == "__main__":
    main()
