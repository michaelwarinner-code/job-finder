"""
Standalone test for pdf_builder.py. Generates real resume/cover letter
content via materials_writer.py for one posting, then builds actual DOCX
and PDF files from it -- proving the full chain (Claude-generated content
-> real files) works before this becomes part of the real pipeline.

    AUTOAPPLY_ANTHROPIC_API_KEY=... python auto-apply/pdf_builder_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from materials_writer import generate_materials
from pdf_builder import build_resume_and_coverletter

# --- Edit these to a real posting ---
COMPANY = "Modo Energy"
JOB_TITLE = "Growth Associate"
JOB_DESCRIPTION = """
The energy transition is the biggest infrastructure buildout in human history. Modo Energy is the data platform at the centre of it.

We build the benchmarking, forecasting, and valuation tools that the world's most serious energy investors, developers, and operators depend on to make decisions. If a battery gets financed, built, or traded anywhere in the world, there's a good chance Modo data was in the room.

Founded in 2019, we're 90+ people across London, New York, Sydney, and Madrid; $30M Series B, AI-native, and moving fast.

This is a rare chance to join a category-defining company at the moment it's scaling globally.

The Role
We're hiring a Growth Associate to help more people discover and sign up to Modo Energy.

This is a generalist role, and one of the most cross-functional in the company. You'll work directly with the Head of Product Marketing and touch almost every team in the business, marketing, product, and beyond, often in the same week. Because Modo runs its Australia and Europe marketing out of this office, you'll also work on a genuinely global scale: understanding what regional teams have built, why, who their customers are, and shaping campaigns for markets you won't always be sitting in.

Day to day, that might mean running a campaign for a new market launch, making a short video that shows what Ko (our AI Analyst) can do, writing an email that re-engages free users, or figuring out why people aren't converting and fixing it. The scope of this role will grow as we do, what it looks like in year two may look very different from day one. We can't promise you a fixed career path here; what we can promise is a lot of real responsibility, fast, and exposure to more of the business than most junior roles offer.

A big part of this role is product marketing. You'll need to get under the skin of what we build, market indices, revenue forecasts, Ko our AI analyst, and help set the standard for how we talk about it. We want to be best-in-class here: creative, sharp, and ahead of the rest of the industry in how we reach and engage our audience. That means having real opinions about what good looks like and the drive to execute on them.

We also want someone we can trust with the words that go out under Modo's name, customer emails, product comms, campaign copy, without needing every draft heavily reviewed. Strong written communication isn't a nice-to-have here; it's one of the main things we're hiring for.

We care about taste. If something looks or sounds wrong, say so.

And if you're excited about the energy transition, you'll fit right in. Modo Energy exists to help capital flow more efficiently into clean energy infrastructure, and understanding how power markets actually work is a big part of the job. If that sounds interesting rather than intimidating, that's a good sign.

Why now: we're at an inflection point in the US, where we've built out a lot of product and are investing heavily in go-to-market. This role is part of the team trying to help Modo scale and win in the US, which means the day-to-day will genuinely vary week to week, and you'll pick up a range of skills quickly that we think are especially valuable if you're entrepreneurial or considering founding something of your own down the line.

What You'll Do
Create content that helps people understand Modo Energy's products, short videos, emails, social posts, demos of Ko in action
Write and own customer-facing communications such as campaign emails, re-engagement sequences, and product comms, to a high bar with minimal need for rewriting
Run campaigns when new markets launch to get the right users to sign up, including for regions (Australia, Europe) you'll coordinate on remotely
Own the metrics that matter for top-of-funnel growth
Know what's converting, what's driving discovery, and where the biggest opportunities are
Report weekly, iterate fast, and make sure every decision we make is grounded in what's actually working
Drive adoption of new features through creative, targeted outreach
Help tell Modo Energy's story as the company scales into new markets
Work closely with product, and with regional teams, to understand context before you market it, you'll need to know enough about what's being built, and for whom, to represent it well
What We're Looking For
We hire for this role from two different directions — people with marketing backgrounds and people with more analytical/data backgrounds — and we're genuinely open to either. What matters more than your degree or your title so far is evidence you're a generalist: someone who's driving, curious, and doesn't need a defined lane to be effective.

The Essentials
A high, demonstrated willingness to learn and to pick up work outside your defined scope, we're looking for people who've shown this already (a founder-type project, something you built or ran independently, anything outside a formal job description)
You've shipped something independently, a project, a campaign, a newsletter, anything you took from idea to live
Strong written communication, clear, well-structured, and right for the reader. We're specifically looking for someone we can trust to draft customer-facing comms without heavy editing
Taste and judgement, you know good from bad and you'll say so
You use AI as a core part of how you work, not just chatbots, but building workflows, automating tasks, and using agents to get things done faster
Curious and resourceful, you figure things out without being told how, and you're comfortable asking the right questions when you don't have full context (you'll need this constantly, given how many teams this role touches)
Nice To Have
Comfortable with design or video tools: Figma, Premiere Pro, After Effects, or similar
An engineering or analytical mindset, you think in systems and would rather automate something than do it manually twice
Some experience with growth or marketing campaigns
An interest in energy, climate, or the transition to clean power
Degree in an analytical field: economics, engineering, maths, physics, or similar (we care more about how you think than what you studied)
Compensation & Equal Opportunity
Base salary range: $80,000–$120,000 per year, depending on experience.
25 days annual leave, medical, dental and vision coverage, and 401(k) with optional employer matching
Modo Energy is an equal opportunity employer - employment decisions are made on the basis of qualifications, merit, and business need. We do not discriminate on the basis of race, color, religion, national origin, sex, age, disability, sexual orientation, gender identity or expression, pregnancy, veteran status, or any other characteristic protected by federal, New York State, or New York City law
For assistance or a reasonable accommodation during the application or interview process, contact us at careers@modoenergy.com
What You Can Expect From Us
At Modo Energy, we believe that exceptional work deserves exceptional reward. We're a high-performance team; ambitious, collaborative, and genuinely motivated by the scale of what we're trying to build.

You'll have real ownership from day one, work alongside some of the brightest people in the industry, and be part of a company that's defining a new category in the global energy market. We're hybrid: everyone works Tuesday to Thursday in office, with Monday and Friday flexible. We offer top-of-market compensation, equity for every employee, and the space to take your career wherever you want it to go.

We're looking for people who want to do the best work of their careers. If that's you, we want to talk.
"""
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "test_output", "pdf_builder_test")
# -------------------------------------


def main():
    print(f"Generating materials for {JOB_TITLE} at {COMPANY}...")
    resume_data, coverletter_data = generate_materials(JOB_DESCRIPTION, COMPANY, JOB_TITLE)

    print(f"Building PDFs into {OUTPUT_DIR}...")
    resume_pdf, cl_pdf = build_resume_and_coverletter(resume_data, coverletter_data, OUTPUT_DIR)

    print(f"\nResume PDF: {resume_pdf} (exists: {os.path.exists(resume_pdf)})")
    print(f"Cover letter PDF: {cl_pdf} (exists: {os.path.exists(cl_pdf)})")
    print("\nOpen both files and confirm they look right before trusting this in the real pipeline.")


if __name__ == "__main__":
    main()
