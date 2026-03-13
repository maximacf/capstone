# tester for db

import sqlite3

import pandas as pd

con = sqlite3.connect("data/mail.db")
df = pd.read_sql("select subject, category from message limit 5", con)
print(df)
