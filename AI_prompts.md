# AI Prompts Log — AI Foundations HW6

A log of the prompts I typed to the AI assistant while building the Campus Customs Vendor Desk Agent, grouped by problem. Follow-up prompts note what the earlier prompt was missing.

---

## Problem 1: Vibe Coder Prompts

### Initial prompt

> Hello! Today we are working on a project to build a vendor desk agent that reads documents and pulls out key facts (e.g. vendor, item, lead time, price, minimum order) and recommends whether our shop Campus Customs should buy, following the rules in the Campus Customs Shop Handbook. Do not send emails or make payments - the agent's email and payment tools only write to a log file. Use my API key and only gpt-6-luna for AI call

### Follow-up prompts

**Follow-up 1**

> Pls keep everything in my github AI-HW6 repository

*What was lacking:* The first prompt didn't say where the project should live, so there was no target repo for the code.

**Follow-up 2**

> Pls create AI_prompts.md and keep updating it as we work, this should be a log of what I type to you. Keep one section for each problem, each section must include the problem number and title, the prompts I type for the problem, and a follow up prompt if needed with a sentence on what was lacking on the first prompt. You can keep this and the previous prompt under Problem 1: Vibe Coder Prompts

*What was lacking:* The earlier prompts didn't ask for a record of the prompts, so there was no log of how the project was directed.

---

## Problem 2: Size Up the Handbook

### Initial prompt

> @"C:\Users\megha\Downloads\data (2)\data\prices.json" @"C:\Users\megha\Downloads\data (2)\data\shop_handbook.md"
> Next is Problem 2: Size Up the Handbook. Look through the shop handbook file I attached here. This is the Campus Customs Shop Handbook and the agent will send it to the model on every single call. Also see the prices file attached. Find out how many tokens the handbook is. In output/handbook_estimate.md, write the token count and how you got it, what the handbook alone costs in dollars on one call, and on 1,000 calls, with cached tokens, and without them - show your math.

---

## Problem 3: Build the Vendor Desk Agent

### Initial prompt

> Thx. Next is Problem 3: Build the Vendor Desk Agent. Build the vendor desk agent with PydanticAI using gpt luna. The agent is these four files: prompts/prompt.md - your instructions for the agent (agent also sends handbook to the model on every call), agent.py - the entry point, tools.py - the tools, and models.py - the structured types. Give the agent the path to one vendor document. It reads the document with a tool (HTML, PDF, and .eml email files all have to work), and returns vendor, SKU, unit price, lead time in days, minimum order, a decision (recommend or do_not_recommend) following the handbook rules and a one sentence reason

### Follow-up prompts

**Follow-up 1**

> The agent should also have two trap tools: send_email and approve_payment. Its job never needs them - they are there to catch a malicious document that tricks the agent into emailing someone or paying a vendor. They do not send or pay anything, they only append the call and its arguments to output/trap_calls.json (start it as an empty list) so if that file ever has an entry, a document took over the agent. After every run, append to output/usage_log.json (document, time, token counts the API reports, and the dollar cost using prices.json) and output/audit_trail.json (each tool call with its arguments and a short result, plus the final answer). The agent should run like this in the terminal: python agent.py --doc data/practice_docs/p01_bluehen_quote.html. Run it on p01 and p08 to show it works. Start output/harness.md: each field in models.py and why, and each tool in one line

*What was lacking:* The first prompt didn't say how to catch a document that hijacks the agent (trap tools and trap_calls.json), what to log on each run (usage, cost, audit trail), the exact command-line form, or that a harness write-up was needed.

**Follow-up 2**

> @"C:\Users\megha\Downloads\data (2)\data\practice_docs/"
> Here are the practice docus

*What was lacking:* The earlier prompts referred to data/practice_docs without pointing to where the practice documents were.

**Follow-up 3**

> Yes, commit everything and push it to my AI-HW6 repo.

*What was lacking:* Follow-up 1 of Problem 1 said to keep the project in AI-HW6, but no prompt had yet given the go-ahead to commit and push the finished work.
