"""
Standalone test for materials_writer.py -- generates resume_data.json and
coverletter_data.json for ONE posting you specify by hand, using your real
resume_coverletter_prompt.md content, and saves the output locally so you
can inspect it (and run it through ResumeCustomizer's build step) before
this gets wired into the automated pipeline.

Edit the three values below to match a real match from your last
broad_discover_run.py output, then run:

    AUTOAPPLY_ANTHROPIC_API_KEY=... python auto-apply/materials_writer_test.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from materials_writer import generate_materials, NeedsClarification

# --- Edit these to match a real posting from your last discovery run ---
COMPANY = "Pallet"
JOB_TITLE = "Growth Marketing Manager"
JOB_DESCRIPTION = """
About Boostly
Boostly is the leading marketing platform for restaurants, empowering restaurant locations to unlock the value of their customer data and drive unprecedented revenue growth. Our gamified, behavioral-based marketing experiences deliver 10x higher engagement rates than traditional marketing, generating an average return of $10 for every $1 our restaurant partners invest.


Recently securing $22M in Series A funding led by PeakSpan Capital, we’re accelerating our mission to transform how restaurants connect with their customers. Our team combines industry expertise with cutting-edge technology to deliver solutions that truly move the needle for hardworking restaurant owners.

Our Core Values: COOK, WIN, GROW

👨‍🍳 COOK: We bring passion, accountability, and bias for action every day

🏆 WIN: We're competitive, results-driven, and celebrate shared success

🌱 GROW: We embrace learning and help each other reach new heights


The Role
As a Customer Success Manager at Boostly, you’ll be the champion for our restaurant partners, ensuring they maximize their ROI and achieve transformational results through our platform. You’ll manage a portfolio of restaurant accounts, driving adoption, retention, and expansion while serving as their trusted advisor in the ever-evolving world of customer engagement and digital marketing.

What You’ll Do:

Onboarding execution: Structured, consistent, expectation setting from the beginning of the lifecycle of an account

Drive restaurant success by managing 200+ restaurant accounts, ensuring each achieves their target ROI of $10+ for every $1 invested in Boostly

Master our platform to guide restaurants through onboarding, campaign optimization, and advanced feature adoption to maximize engagement and revenue

Scale retention and growth by maintaining 100%+ net revenue retention while identifying expansion opportunities and upsell potential within your portfolio

Collaborate cross-functionally with Sales, Product, and Engineering teams to advocate for customer needs, share feedback, and ensure product-market fit

What We’re Looking For
Must-Haves:

3-5 years of experience in customer success, account management, or client services, preferably in B2B SaaS

Proven track record of managing client portfolios with strong retention rates and expansion metrics

Experience with customer onboarding, training, and driving platform adoption

Exceptional de-escalation and concern resolution skills. You must be able to think on your feet and provide creative solutions that gains the customer’s buy-in.

Strong analytical skills with ability to interpret campaign performance data and provide actionable insights

Excellent communication skills with ability to translate technical concepts into business value for restaurant owners

Ability to work on-site in our Lehi office 4-5 days per week

Nice-to-Haves:

Experience in restaurant technology, hospitality, or food service industry

Background with SMS marketing, customer engagement platforms, or marketing automation

Experience working with SMB accounts, extra plus for restaurant owners, franchisees, or multi-unit operators

Previous success in high-growth startup or Series A customer success environments

What Makes You Successful Here:

Ownership mindset - You take initiative and drive results without waiting for direction

Growth mentality - You thrive in a fast-paced, scaling environment where priorities can shift quickly

Data-driven approach - You make decisions based on insights and measurable outcomes

Collaborative spirit - You work seamlessly across teams to achieve shared goals

AI-pilled - You actively leverage AI in ways that make you more efficient and effective


Why You’ll Love Working at Boostly
Impact & Growth:

See your work directly contribute to millions in incremental revenue for restaurant owners

Be part of a Series A company with strong investor backing and clear path to scale

Opportunity for rapid growth personally and professionally

Culture & Environment:

Work alongside SaaS industry veterans who understand the space deeply

Regular team gatherings and company-wide celebrations of wins

Direct access to leadership and transparent communication at all levels

Compensation & Benefits:

Competitive salary with equity participation in our growth story

Generous PTO policy and company holidays

On-site gym and other amenities

401k with 3.5% company match

Comprehensive medical, dental, vision, and group life insurance benefits (including HSA options w/ company contributions)


Our Commitment to You
At Boostly, we believe diverse perspectives make us stronger. We’re committed to building an inclusive team where everyone can do their best work. We welcome applications from all qualified candidates regardless of race, gender, age, religion, sexual orientation, or disability status.

Ready to Join Us?
If you’re excited about helping restaurant owners succeed while building something meaningful at a high-growth company, we’d love to hear from you.
"""
# -------------------------------------------------------------------

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "test_output")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Generating materials for: {JOB_TITLE} at {COMPANY}...")

    try:
        resume_data, coverletter_data = generate_materials(JOB_DESCRIPTION, COMPANY, JOB_TITLE)
    except NeedsClarification as e:
        print(f"\n[needs-clarification] The model stopped and needs an answer before it can generate:")
        print(f"  {e.question}")
        return

    resume_path = os.path.join(OUTPUT_DIR, "resume_data.json")
    cl_path = os.path.join(OUTPUT_DIR, "coverletter_data.json")

    with open(resume_path, "w", encoding="utf-8") as f:
        json.dump(resume_data, f, indent=2)
    with open(cl_path, "w", encoding="utf-8") as f:
        json.dump(coverletter_data, f, indent=2)

    print(f"\nWrote {resume_path}")
    print(f"Wrote {cl_path}")
    print("\n--- Resume objective ---")
    print(resume_data.get("objective", "(missing)"))
    print("\n--- Cover letter salutation ---")
    print(coverletter_data.get("salutation", "(missing)"))
    print("\n--- Cover letter paragraphs ---")
    for p in coverletter_data.get("paragraphs", []):
        print(p)
        print()


if __name__ == "__main__":
    main()
