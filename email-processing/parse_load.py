# Normalize and Classify

# we ingested the raw mails; now we want to parse them 
# so Parse load: reads  raw messages, cleans and classifies them, and stores structured rows in message
from classification import HybridClassifier, detect_urgency, html_to_text
from store_db import connect, log_classification_event, source_key, upsert_message

CLASSIFIER = HybridClassifier()

# MAIN PROCESSING LOOP: Fetch all new raw emails (ones not yet in the message table).
def main():
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT r.id, r.internet_id, r.received_dt, r.from_addr, r.subject, r.body_html
        FROM raw_message r
        LEFT JOIN message m ON m.id = r.id
        WHERE m.id IS NULL
        ORDER BY r.received_dt DESC
        """)

    for mid, iid, rdt, frm, subj, body_html in cur.fetchall():
        body_text = html_to_text(body_html)
        result = CLASSIFIER.classify(subj or "", body_text, frm)
        category = result.label
        domain = (frm.split("@",1)[1].lower()) if frm and "@" in frm else None
        urgency = detect_urgency(subj, body_text)
        # insert into message:
        upsert_message(con, {
            "id": mid,
            "internet_id": iid,
            "received_dt": rdt,
            "from_addr": frm,
            "subject": subj,
            "body_text": body_text,
            "body_html": body_html,
            "category": category,
            "source_hash": source_key(subj, frm, rdt),
            "manual_category": None,
            "from_domain": domain,
            # new/optional fields:
            "urgency": urgency,
            "language": None,
            "has_attachment": 0,
            "thread_id": None,
            "to_addresses": None,
            "cc_addresses": None,
            "entities": None,
        })
        
        #  audit row to track model versions, debugging
        log_classification_event(
            con,
            message_id=mid,
            category_auto=category,
            rule_name=result.detail or result.source,
            confidence=result.confidence,
        )
    print("Parse + load done.")

if __name__ == "__main__":
    main()
