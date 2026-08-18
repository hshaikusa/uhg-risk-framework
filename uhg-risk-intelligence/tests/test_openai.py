import os
from openai import OpenAI

def main():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("FAIL: OPENAI_API_KEY not set in environment")
        return

    print(f"Key loaded (length={len(key)})")

    client = OpenAI(api_key=key)
    try:
        resp = client.chat.completions.create(
            model=os.getenv("FAST_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": "Reply with exactly: OpenAI is working"}],
            max_tokens=10,
        )
        print("SUCCESS:", resp.choices[0].message.content)
    except Exception as e:
        print("FAIL:", type(e).__name__, str(e))

if __name__ == "__main__":
    main()