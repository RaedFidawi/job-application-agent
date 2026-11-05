"""Prompts for each LLM step."""

SYSTEM = """You are an expert technical recruiter and career coach helping a \
candidate apply for a specific job. You are rigorously honest: you never invent \
experience, employers, titles, dates, metrics, degrees or skills that are not in \
the candidate's resume. You may reword, reorder, emphasise and de-emphasise, \
but every claim must be traceable to the original resume."""

ANALYZE_JOB = """Analyse this job posting. Ignore boilerplate such as benefits, \
EEO statements and site navigation.

<job_posting>
{job_text}
</job_posting>"""

ASSESS_FIT = """Compare the candidate's resume against the job analysis and give \
an honest fit assessment. Only count a requirement as a strength if the resume \
gives concrete evidence for it.

<job_analysis>
{job}
</job_analysis>

<resume>
{resume}
</resume>"""

TAILOR_RESUME = """Rewrite the candidate's resume for this specific role.

- Lead with the experience most relevant to the role; trim or drop what isn't.
- Rewrite bullets to use the job's vocabulary where the underlying work matches.
- Keep every employer, title, date, number and degree exactly as in the original.
- Do not add skills or accomplishments the original doesn't support.
- Output only the resume, in clean Markdown, with no commentary.

<job_analysis>
{job}
</job_analysis>

<fit_report>
{fit}
</fit_report>

<original_resume>
{resume}
</original_resume>"""

COVER_LETTER = """Write a cover letter for this role.

- 250-350 words, three or four paragraphs, confident and specific, no clichés.
- Open with why this role and company, not "I am writing to apply".
- Connect two or three concrete achievements from the resume to the job's needs.
- Address the most important gap honestly if it's relevant, framed constructively.
- Output only the letter text, with no commentary or placeholders for the date \
or address.

<job_analysis>
{job}
</job_analysis>

<fit_report>
{fit}
</fit_report>

<resume>
{resume}
</resume>"""

FACT_CHECK = """Check the tailored resume and cover letter against the original \
resume. Flag every claim that is not supported by the original: invented skills, \
inflated titles or scope, changed dates or numbers, or achievements that aren't \
there. Rewording and reordering are fine. Pass only if there are no such issues.

<original_resume>
{resume}
</original_resume>

<tailored_resume>
{resume_draft}
</tailored_resume>

<cover_letter>
{cover_letter_draft}
</cover_letter>"""

REVISE = """Revise the tailored resume and cover letter to address the feedback \
below. Change only what the feedback requires and keep everything else. Stay \
strictly truthful to the original resume, even if the feedback asks otherwise.

<feedback>
{feedback}
</feedback>

<job_analysis>
{job}
</job_analysis>

<original_resume>
{resume}
</original_resume>

<current_tailored_resume>
{resume_draft}
</current_tailored_resume>

<current_cover_letter>
{cover_letter_draft}
</current_cover_letter>"""
