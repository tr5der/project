"""A minimal agent integration; extend here with OpenAI Agents SDK, A2A tools, audit, etc."""
import asyncio
from pathlib import Path
from .settings import ROOT, OPENAI_MODEL


def file_text(name):
    return (ROOT / "harness" / name).read_text(encoding="utf-8")


def normalize_history(history):
    """Never pass Gradio content-part dictionaries or vendor-specific history to Responses."""
    return [{"role": m["role"], "content": str(m["content"])}
            for m in history if m.get("role") in ("user", "assistant")]


def answer_sync(history, memory, question):
    from openai import OpenAI
    instructions = file_text("instructions.md")
    if memory:
        instructions += "\n\nSaved memory for the current user:\n" + memory[:12000]
    response = OpenAI().responses.create(
        model=OPENAI_MODEL,
        instructions=instructions,
        input=normalize_history(history) + [{"role": "user", "content": question}],
        tools=[],
    )
    sources = []
    for item in response.output or []:
        for part in getattr(item, "content", []) or []:
            for ann in getattr(part, "annotations", []) or []:
                if getattr(ann, "type", "") == "url_citation":
                    url = getattr(ann, "url", "")
                    if url.startswith(("https://", "http://")):
                        data = {"title": getattr(ann, "title", "") or url, "url": url}
                        if data not in sources:
                            sources.append(data)
    return response.output_text or "No text returned.", sources


async def answer(history, memory, question):
    return await asyncio.to_thread(answer_sync, history, memory, question)


def summarize_sync(old_memory, messages):
    from openai import OpenAI
    transcript = "\n".join(f'{m["role"]}: {m["content"]}' for m in messages)
    result = OpenAI().responses.create(
        model=OPENAI_MODEL,
        instructions=file_text("memory_instructions.md"),
        input=f"Prior memory:\n{old_memory}\n\nRecent chat:\n{transcript}"[:60000],
    )
    if not result.output_text or not result.output_text.strip():
        raise RuntimeError("Model returned no memory summary")
    return result.output_text.strip()


async def summarize(old_memory, messages):
    return await asyncio.to_thread(summarize_sync, old_memory, messages)
