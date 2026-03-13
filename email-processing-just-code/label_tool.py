import pandas as pd
import streamlit as st
from classification import CANONICAL_LABELS
from database import get_engine
from store_db import connect

CATEGORIES = CANONICAL_LABELS


def load_unlabeled(limit=1):
    df = pd.read_sql(
        """
        SELECT id, subject, body_text, category, manual_category
        FROM message
        WHERE manual_category IS NULL
        ORDER BY received_dt DESC NULLS LAST
        LIMIT %s
        """,
        get_engine(),
        params=(limit,),
    )
    return df


def update_label(msg_id, label):
    con = connect()
    try:
        con.execute(
            "UPDATE message SET manual_category = ?, updated_ts = CURRENT_TIMESTAMP WHERE id = ?",
            (label, msg_id),
        )
        con.commit()
    finally:
        con.close()


def main():
    st.title("📧 Email Labeling Tool")

    df = load_unlabeled(limit=1)
    if df.empty:
        st.success("✅ All messages labeled!")
        return

    msg = df.iloc[0]
    st.subheader(msg["subject"])
    st.caption(f"Model suggestion: {msg['category'] or 'unknown'}")
    st.write(msg["body_text"][:2000])  # limit text length for now

    st.markdown("---")
    chosen_label = st.radio("Select category:", CATEGORIES)

    if st.button("Save label"):
        update_label(msg["id"], chosen_label)
        st.success(f"Labeled as: {chosen_label}")
        st.experimental_rerun()  # load next email


if __name__ == "__main__":
    main()
