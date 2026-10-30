import os
from functools import lru_cache
from typing import Literal, Type, TypeVar

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

load_dotenv()

Task = Literal["bullets", "parse_jd", "match", "cv", "gaps", "courses", "revise", "swap", "letter",
               "revise_letter"]

# Each task gets the cheapest model that does it well. Override a model with an env var,
# e.g. MODEL_GAPS=gpt-6-luna to cut cost, or MODEL_PARSE_JD=gpt-6-sol for harder postings.
TASK_MODELS: dict[Task, tuple[str, str]] = {  # task -> (model, reasoning effort)
    "bullets": ("gpt-6-luna", "low"),      # rewrite one item's own text into bullets
    "parse_jd": ("gpt-6-luna", "medium"),  # extraction from long, noisy pasted text
    "match": ("gpt-6-sol", "medium"),      # judgment: what the profile shows vs. what the job asks
    "cv": ("gpt-6-sol", "medium"),         # tailored writing that must stay truthful
    "gaps": ("gpt-6-sol", "medium"),       # technical advice: realistic, correct project plans
    "courses": ("gpt-6-luna", "medium"),   # web search for courses; search results make the input long
    "revise": ("gpt-6-sol", "low"),        # small edits to a CV on request that must stay truthful
    "swap": ("gpt-6-sol", "medium"),       # tailored bullets for one item swapped onto the CV, as in "cv"
    "letter": ("gpt-6-sol", "medium"),     # a short, natural cover letter that must stay truthful
    "revise_letter": ("gpt-6-sol", "low"), # edits to a cover letter on request
}

T = TypeVar("T", bound=BaseModel)


def model_for(task: Task) -> str:
    return os.getenv(f"MODEL_{task.upper()}", TASK_MODELS[task][0])


@lru_cache(maxsize=None)
def _llm(model: str, effort: str) -> ChatOpenAI:
    return ChatOpenAI(model=model, reasoning_effort=effort)


def extract_structured(task: Task, system_prompt: str, user_text: str, schema: Type[T],
                       web_search: bool = False) -> T:
    llm = _llm(model_for(task), TASK_MODELS[task][1])
    messages = [("system", system_prompt), ("human", user_text)]
    if not web_search:
        return llm.with_structured_output(schema).invoke(messages)
    # OpenAI's built-in web search (Responses API); the final answer is still parsed into the schema.
    result = llm.with_structured_output(schema, tools=[{"type": "web_search"}], strict=True,
                                        include_raw=True).invoke(messages)
    if result["parsing_error"] is not None:
        raise result["parsing_error"]
    if result["parsed"] is None:
        raise ValueError("The model returned no structured answer after searching.")
    return result["parsed"]
