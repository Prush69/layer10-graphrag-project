"""
Neo4j Storage Backend for Layer10 Memory Graph
"""
import json
import os
from neo4j import GraphDatabase
from typing import Optional

# We will let memory_graph.py import this to avoid circular imports.
# The class signature matches GraphStorageBackend exactly.

class Neo4jBackend:
    def __init__(self):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        if "neo4j+s" in uri:
            uri = uri.replace("neo4j+s", "bolt+s")
        user = os.getenv("NEO4J_USERNAME", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")
        print(f"  [DB] Connecting to {uri} as {user}...")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        # Warm up connection
        try:
            with self.driver.session() as session:
                session.run("RETURN 1")
            print("  [DB] Connection successful")
        except Exception as e:
            print(f"  [DB] Connection failed: {e}")
            raise
        
    def close(self):
        self.driver.close()

    def _dict_to_props(self, attrs):
        props = {}
        for k, v in attrs.items():
            if isinstance(v, (dict, list)):
                props[k] = json.dumps(v)
            elif v is None:
                props[k] = "" # Neo4j driver rejects None as properties
            else:
                props[k] = v
        return props

    def _props_to_dict(self, props):
        res = dict(props)
        for k, v in res.items():
            if isinstance(v, str):
                if (v.startswith('{') and v.endswith('}')) or (v.startswith('[') and v.endswith(']')):
                    try:
                        res[k] = json.loads(v)
                    except:
                        pass
        return res

    def add_node(self, node_id: str, **attrs) -> bool:
        props = self._dict_to_props(attrs)
        props['id'] = node_id
        
        query = """
        MERGE (n:Node {id: $id})
        ON CREATE SET n += $props
        RETURN n
        """
        with self.driver.session() as session:
            res = session.run(query, id=node_id, props=props)
            return len(list(res)) > 0

    def has_node(self, node_id: str) -> bool:
        query = "MATCH (n:Node {id: $id}) RETURN count(n) > 0 AS exists"
        with self.driver.session() as session:
            return session.run(query, id=node_id).single()["exists"]

    def get_node(self, node_id: str) -> Optional[dict]:
        query = "MATCH (n:Node {id: $id}) RETURN n"
        with self.driver.session() as session:
            res = session.run(query, id=node_id).single()
            if res:
                return self._props_to_dict(res["n"])
            return None

    def update_node(self, node_id: str, **attrs):
        props = self._dict_to_props(attrs)
        query = """
        MATCH (n:Node {id: $id})
        SET n += $props
        """
        with self.driver.session() as session:
            session.run(query, id=node_id, props=props)

    def add_edge(self, source: str, target: str, key: str = None, **attrs) -> bool:
        props = self._dict_to_props(attrs)
        if key:
            props['_key'] = key
            
        rel_type = props.get('type', 'RELATES_TO')
        if not isinstance(rel_type, str): rel_type = 'RELATES_TO'
        rel_type = rel_type.upper()
        safe_rel_type = "".join([c for c in rel_type if c.isalnum() or c == '_'])
        if not safe_rel_type: safe_rel_type = 'RELATES_TO'
        
        query = f"""
        MERGE (a:Node {{id: $source}})
        MERGE (b:Node {{id: $target}})
        MERGE (a)-[r:{safe_rel_type}]->(b)
        SET r += $props
        """
        with self.driver.session() as session:
            session.run(query, source=source, target=target, props=props)
        return True

    def get_out_edges(self, node_id: str) -> list[dict]:
        query = "MATCH (n:Node {id: $id})-[r]->(m) RETURN r, m.id AS target"
        results = []
        with self.driver.session() as session:
            for record in session.run(query, id=node_id):
                edge = self._props_to_dict(record["r"])
                edge["_source"] = node_id
                edge["_target"] = record["target"]
                edge["_key"] = edge.get("_key")
                results.append(edge)
        return results

    def get_in_edges(self, node_id: str) -> list[dict]:
        query = "MATCH (n)-[r]->(m:Node {id: $id}) RETURN r, n.id AS source"
        results = []
        with self.driver.session() as session:
            for record in session.run(query, id=node_id):
                edge = self._props_to_dict(record["r"])
                edge["_source"] = record["source"]
                edge["_target"] = node_id
                edge["_key"] = edge.get("_key")
                results.append(edge)
        return results

    def get_all_nodes(self) -> list[tuple[str, dict]]:
        query = "MATCH (n:Node) RETURN n"
        results = []
        with self.driver.session() as session:
            for record in session.run(query):
                node = record["n"]
                props = self._props_to_dict(node)
                results.append((props.get("id"), props))
        return results

    def get_all_edges(self) -> list[dict]:
        query = "MATCH (n)-[r]->(m) RETURN r, n.id AS source, m.id AS target"
        results = []
        with self.driver.session() as session:
            for record in session.run(query):
                edge = self._props_to_dict(record["r"])
                edge["_source"] = record["source"]
                edge["_target"] = record["target"]
                edge["_key"] = edge.get("_key")
                results.append(edge)
        return results

    def node_count(self) -> int:
        query = "MATCH (n:Node) RETURN count(n) AS c"
        with self.driver.session() as session:
            return session.run(query).single()["c"]

    def edge_count(self) -> int:
        query = "MATCH ()-[r]->() RETURN count(r) AS c"
        with self.driver.session() as session:
            return session.run(query).single()["c"]

    def clear(self):
        query = "MATCH (n) DETACH DELETE n"
        with self.driver.session() as session:
            session.run(query)
