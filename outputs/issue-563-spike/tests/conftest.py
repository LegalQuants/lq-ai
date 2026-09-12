import os

# The experiment must remain local even in a shell configured for remote tracing.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
