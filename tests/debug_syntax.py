import tree_sitter
import tree_sitter_rust

language = tree_sitter.Language(tree_sitter_rust.language())
parser = tree_sitter.Parser(language)

# Invalid Rust code
invalid_code = """
fn take_damage(&mut self, amount: i32) {
    println!("Hello {}", amount)
} // missing semicolon
"""

print("Parsing invalid code:")
print(repr(invalid_code))

tree = parser.parse(bytes(invalid_code, "utf8"))
print(f"Tree root type: {tree.root_node.type}")


def print_tree(node, depth=0):
    indent = "  " * depth
    print(f"{indent}{node.type}: {repr(node.text[:50]) if node.text else ''}")
    for child in node.children:
        print_tree(child, depth + 1)


print("\nTree structure:")
print_tree(tree.root_node)


# Check for ERROR nodes
def has_error_node(node):
    if node.type == "ERROR":
        print(f"Found ERROR node: {node}")
        return True
    for child in node.children:
        if has_error_node(child):
            return True
    return False


has_errors = has_error_node(tree.root_node)
print(f"\nHas errors: {has_errors}")
