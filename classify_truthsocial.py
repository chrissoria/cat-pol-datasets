#!/usr/bin/env python3
"""Classify Truth Social posts using the existing ensemble workflow."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

CAT_COLS = [
    "cat_attacking_individual",
    "cat_attacking_opposition",
    "cat_threatening_intl",
    "cat_enacting_aggressive",
    "cat_enacting_nonaggressive",
    "cat_deescalating",
    "cat_praising_endorsing",
    "cat_self_promotion",
    "cat_other",
]

CAT_NAMES = [
    "Attacking individual — targeting a specific person by name",
    "Attacking political opposition — targeting Democrats, a party, or political group broadly",
    "Threatening/escalating internationally — conditional threats, tariff warnings, military posturing",
    "Enacting aggressive policy — imposing tariffs, sanctions, bans, military action (already done)",
    "Enacting non-aggressive policy — signing bills, executive orders, domestic programs, appointments",
    "De-escalating conflict — toning down, announcing deals, peace talks, ceasefire",
    "Praising/endorsing — positive statements about a person, leader, ally",
    "Self-promotion — boasting about achievements, economy, polls, ratings",
    "Other — does not fit any above category",
]

CAT_SYSTEM_PROMPT = (
    'Classification guidance per category:\n\n'
    '- Attacking individual — targeting a specific person by name: Assign "Attacking individual" when a text explicitly criticizes or attacks a specific person by name, and not when it simply mentions or praises them, or shares a link discussing them without commentary. Do not assign this category to texts that broadly target a party, group, or ideology unless they specifically name and attack an individual.\n'
    '- Attacking political opposition: Assign this category when a text explicitly criticizes or attacks Democrats, a party, or a political group broadly, and not just a specific individual. Do not assign this category when a text is just sharing a link or when the criticism is directed at a specific person rather than a broader group or party.\n'
    '- Enacting aggressive policy: Assign when the text explicitly describes or reports a specific aggressive action that has been taken, such as imposing tariffs, enforcing sanctions, implementing bans, or conducting military operations. Do not assign to URLs or links alone.\n'
    '- Enacting non-aggressive policy: Assign when the text explicitly mentions the implementation of a domestic policy, program, or appointment through actions like signing bills or executive orders, and does not involve aggressive actions.\n'
    '- Praising/endorsing: Assign when a text contains explicit positive statements or endorsements about a specific person, leader, or ally. Do not assign when a text merely reports on someone\'s actions or shares a link without expressing clear positive sentiment.\n'
    '- URL/link only: Do not assign — filter these to Other instead.\n'
)


def classify_truthsocial_posts(
    updated: pd.DataFrame,
    log: logging.Logger,
    checkpoint_dir: Path,
    hf_api_key: str | None,
    tag: str = "[TruthSocial]",
) -> pd.DataFrame:
    """Apply ensemble category labels to new Truth Social text posts."""
    updated = updated.copy()

    try:
        import cat_pol as pol

        openai_key = os.getenv("OPENAI_API_KEY")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        google_key = os.getenv("GOOGLE_API_KEY")

        if hf_api_key and openai_key and anthropic_key and google_key:
            for col in CAT_COLS:
                if col not in updated.columns:
                    updated[col] = pd.NA

            needs_classify = updated[
                (updated["text"].fillna("").str.strip().str.len() > 20)
                & (updated["cat_other"].isna())
                & (pd.to_datetime(updated["datetime"], errors="coerce") >= "2024-11-05")
            ]
            if len(needs_classify) > 0:
                log.info(f"{tag} Classifying {len(needs_classify)} new text posts (5-model ensemble)...")
                try:
                    result = pol.classify(
                        input_data=needs_classify["text"].tolist(),
                        categories=CAT_NAMES,
                        document_context="Trump Truth Social posts",
                        system_prompt=CAT_SYSTEM_PROMPT,
                        models=[
                            ("meta-llama/llama-4-maverick-17b-128e-instruct-fp8:novita", "huggingface", hf_api_key, {"creativity": 0}),
                            ("qwen/qwen3-32b-fp8:novita", "huggingface", hf_api_key, {"creativity": 0}),
                            ("deepseek/deepseek-v3.2:novita", "huggingface", hf_api_key, {"creativity": 0}),
                        ],
                        add_other=False,
                        check_verbosity=False,
                        safety=True,
                        filename="truthsocial_classify_checkpoint",
                        save_directory=str(checkpoint_dir),
                        thinking_budget=0,
                    )
                    consensus_cols = [c for c in result.columns if "consensus" in c]
                    for i, (orig_idx, _) in enumerate(needs_classify.iterrows()):
                        if i < len(result):
                            for cat_col, cons_col in zip(CAT_COLS, consensus_cols):
                                updated.at[orig_idx, cat_col] = result.iloc[i].get(cons_col, 0)
                    classified = result["processing_status"].eq("success").sum()
                    log.info(f"{tag} Classified {classified}/{len(needs_classify)} posts")
                except Exception as e:
                    log.warning(f"{tag} Classification failed: {e}")
            else:
                log.info(f"{tag} No new posts to classify")
        else:
            log.warning(f"{tag} Missing API keys for classification (need HF, OpenAI, Anthropic, Google)")
    except Exception as e:
        log.warning(f"{tag} Could not classify posts: {e}")

    return updated
