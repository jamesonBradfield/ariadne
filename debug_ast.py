import tree_sitter
import tree_sitter_rust
from profiles.rust_profile import RustProfile

def debug_query():
    language = tree_sitter.Language(tree_sitter_rust.language())
    parser = tree_sitter.Parser(language)
    
    with open("test.rs", "rb") as f:
        source = f.read()
        
    tree = parser.parse(source)
    
    profile = RustProfile()
    query_str = profile.get_query("take_damage")
    
    try:
        query = tree_sitter.Query(language, query_str.encode("utf-8"))
        query_cursor = tree_sitter.QueryCursor(query)
        captures = query_cursor.captures(tree.root_node)
        
        print(f"Query:\n{query_str}")
        print(f"\nCaptures: {captures}")
    except Exception as e:
        print(f"Failed to compile query: {e}")

if __name__ == "__main__":
    debug_query()
