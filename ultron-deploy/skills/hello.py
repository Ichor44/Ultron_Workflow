NAME = "hello"
DESCRIPTION = "Greets the user by name."
PERMISSIONS: set = set()
TRIGGERS = ["greet", "hello", "say hi", "introduction"]

def run(name="world", **kwargs):
    return "Hello, %s!" % name
