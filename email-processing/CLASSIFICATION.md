# Email Classification Workflow

## 1. Data flow
1. `ingest_raw.py` pulls Outlook messages into `raw_message`.
2. `parse_load.py` normalizes HTML, calculates urgency, and runs the hybrid classifier.
3. Auto labels plus metadata are stored in `message`, with provenance saved to `classification_event`.

## 2. Manual labeling loop
1. Start labeling via either interface:
   - Streamlit UI: `streamlit run label_tool.py`
   - Terminal CLI (no browser required): `python label_cli.py`
2. Review each email, apply one of the canonical labels, and save.  
   Both tools use the exact same label set as the classifier, so there is no drift.

## 3. Build a training set
Use the helper script to export data for fine-tuning:
```bash
python prepare_training_data.py --output data/training_set.csv
```
- Default export only includes manually labeled rows; pass `--include-auto` to add weak labels.
- Switch to JSONL if your training pipeline prefers it: `--format jsonl`.

## 4. Train an LLM / classifier
1. Inspect the CSV, balance classes, and augment text if needed (subject + truncated body provided).
2. Fine-tune your target model (OpenAI, Azure, HuggingFace, etc.) using the exported data.
3. Record the deployed model name/endpoints and its expected label schema.

## 5. Plug the LLM into production
1. Set environment variables:
   - `OPENAI_API_KEY` (or compatible key)  
   - `LLM_MODEL` (e.g., `gpt-4o-mini`)  
   - `USE_LLM_CLASSIFIER=1`
2. `parse_load.py` now routes low-confidence cases to the LLM and logs the decision source.

## 6. Iterate
1. Periodically re-run `prepare_training_data.py` to capture new human labels.
2. Retrain or refresh the LLM with the expanded dataset.
3. Monitor `classification_event` for drift (e.g., % coming from LLM vs. rules).
