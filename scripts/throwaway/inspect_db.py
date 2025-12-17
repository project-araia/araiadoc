import sys

import psycopg2


def get_first_row(
    db_name, user, password, host="localhost", port="5432", table_name="semantic_scholar", corpus_id="54995"
):
    try:
        # Connect to your postgres DB
        conn = psycopg2.connect(dbname=db_name, user=user, password=password, host=host, port=port)
        cur = conn.cursor()

        # Simple query to get one row
        query = f"SELECT * FROM {table_name} WHERE corpus_id = {corpus_id} LIMIT 5;"  # noqa
        print(f"Executing: {query}")

        cur.execute(query)

        # Fetch result
        rows = cur.fetchall()

        if rows:
            for row in rows:
                # getting column names
                colnames = [desc[0] for desc in cur.description]
                print("\nFirst row found:")
                print("-" * 30)
                for i, val in enumerate(row):
                    print(f"{colnames[i]}: {val} (Type: {type(val)})")
        else:
            print("Table is empty or not found.")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python inspect_db.py <dbname> <user> <password> [host] [port] [table_name] [corpus_id]")
        sys.exit(1)

    dbname = sys.argv[1]
    user = sys.argv[2]
    password = sys.argv[3]
    corpus_id = sys.argv[4]

    # defaults
    host = sys.argv[4] if len(sys.argv) > 4 else "localhost"
    port = sys.argv[5] if len(sys.argv) > 5 else "5432"
    table_name = sys.argv[6] if len(sys.argv) > 6 else "s2orc_meta"
    corpus_id = sys.argv[7] if len(sys.argv) > 7 else "54995"

    get_first_row(dbname, user, password, host, port, table_name, corpus_id)
