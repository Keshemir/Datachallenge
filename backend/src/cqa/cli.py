import argparse
from pathlib import Path

from .inputs import default_checklist, normalize_conversation
from .models import DatasetEnvelope
from .settings import Settings
from .storage import Store


def main():
    parser = argparse.ArgumentParser(description="Import organizer JSON without invoking an LLM")
    parser.add_argument("dataset", type=Path, help="Path to the organizer API JSON response")
    args = parser.parse_args()
    envelope = DatasetEnvelope.model_validate_json(args.dataset.read_text(encoding="utf-8-sig"))
    store = Store(Settings.from_env().db_path)
    store.initialize()
    store.save_checklist(default_checklist())
    keys = store.save_conversations([normalize_conversation(r) for r in envelope.data.records])
    store.save_dataset(
        envelope.data.dataset_group_id, [normalize_conversation(r) for r in envelope.data.records]
    )
    print(
        f"Imported {len(keys)} conversations from {envelope.data.dataset_group_id}; no model calls made."
    )


if __name__ == "__main__":
    main()
