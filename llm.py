from typing import Type, TypeVar

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

load_dotenv()

MODEL = "gpt-5-mini"
_llm = ChatOpenAI(model=MODEL)

T = TypeVar("T", bound=BaseModel)


def extract_structured(system_prompt: str, user_text: str, schema: Type[T]) -> T:
    structured_llm = _llm.with_structured_output(schema)
    return structured_llm.invoke([
        ("system", system_prompt),
        ("human", user_text),
    ])
