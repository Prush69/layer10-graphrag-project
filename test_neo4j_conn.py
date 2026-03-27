import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

def test_conn(uri, user, pwd):
    print(f"Testing {uri} with user {user}...")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, pwd))
        with driver.session() as session:
            res = session.run("RETURN 1 AS one").single()
            print(f"SUCCESS: {res['one']}")
        driver.close()
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False

uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USERNAME")
pwd = os.getenv("NEO4J_PASSWORD")

if not test_conn(uri, user, pwd):
    # Try username 'neo4j'
    test_conn(uri, "neo4j", pwd)
    # Try bolt+s
    if uri.startswith("neo4j+s"):
        bolt_uri = uri.replace("neo4j+s", "bolt+s")
        test_conn(bolt_uri, user, pwd)
        test_conn(bolt_uri, "neo4j", pwd)
