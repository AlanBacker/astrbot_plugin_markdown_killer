import sys
from unittest.mock import MagicMock

# Mock astrbot modules
sys.modules["astrbot"] = MagicMock()
sys.modules["astrbot.api"] = MagicMock()
sys.modules["astrbot.api.event"] = MagicMock()
# sys.modules["astrbot.api.star"] = MagicMock() # Don't mock the whole module with MagicMock
sys.modules["astrbot.api.provider"] = MagicMock()

# Create a dummy Star class
class Star:
    def __init__(self, context):
        pass

# Create a dummy register decorator
def register(*args, **kwargs):
    def decorator(cls):
        return cls
    return decorator

# Mock the star module specifically
mock_star_module = MagicMock()
mock_star_module.Star = Star
mock_star_module.register = register
sys.modules["astrbot.api.star"] = mock_star_module

from main import MarkdownKillerPlugin

# Mock Context
class MockContext:
    pass

def remove_markdown(text: str) -> str:
    plugin = MarkdownKillerPlugin(MockContext())
    return plugin.remove_markdown(text)

def test():
    test_cases = [
        # Basic Markdown
        ("Hello **World**", "Hello World"),
        ("`code`", "code"),
        ("# Header", "Header"),
        ("> Quote", "Quote"),
        ("- List item", "List item"),
        
        # Code Blocks (Optimized)
        ("```python\nprint('hello')\n```", "print('hello')\n"),
        ("```json{\"a\":1}```", "json{\"a\":1}"),
        ("```\nplain\n```", "plain\n"),
        
        # Math Safety (The core fix)
        ("3*4*5", "3*4*5"),
        ("a * b * c", "a * b * c"),
        ("f(x) = x*y", "f(x) = x*y"),
        
        # Italics (Should still work for common cases)
        ("*italic*", "italic"),
        ("This is *italic* text", "This is italic text"),
        ("_italic_", "italic"),
        ("This is _italic_ text", "This is italic text"),
        
        # Edge cases
        ("user_name", "user_name"), # Should not be treated as italic
        ("not * italic *", "not * italic *"), # Spaces inside stars -> not italic in standard markdown usually
    ]

    print("Running tests...")
    failed = False
    for original, expected in test_cases:
        cleaned = remove_markdown(original)
        if cleaned != expected:
            print(f"[FAIL] Input: {repr(original)}")
            print(f"       Got:   {repr(cleaned)}")
            print(f"       Want:  {repr(expected)}")
            failed = True
        else:
            print(f"[PASS] {repr(original)} -> {repr(cleaned)}")
    
    if failed:
        print("\nSome tests FAILED.")
        exit(1)
    else:
        print("\nAll tests PASSED.")

if __name__ == "__main__":
    test()
