import io
import logging
import sys
from typing import Optional

import pdfplumber
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.units import inch
from reportlab.lib import colors
from models import Resume, Links

logging.basicConfig(level=logging.INFO)

# Exact A4 in points (ReportLab default A4 is very close; we pin to spec)
A4_POINTS = (595, 842)


def _pdf_page_count(pdf_bytes: bytes) -> int:
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return len(pdf.pages)
    except Exception as e:
        logging.warning("Could not count PDF pages: %s", e)
        return 0


def _build_resume_pdf_bytes(resume_data: Resume, base_font_pt: float) -> bytes:
    """
    Render resume PDF at A4 with base body font size base_font_pt (points).
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4_POINTS,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )

    page_width_available = A4_POINTS[0] - doc.leftMargin - doc.rightMargin

    styles = getSampleStyleSheet()

    primary_color = colors.HexColor("#1976D2")
    secondary_color = colors.HexColor("#455A64")
    text_color = colors.HexColor("#212121")
    light_text = colors.HexColor("#757575")

    b = float(base_font_pt)
    style_name = ParagraphStyle(
        name="Name",
        parent=styles["Heading1"],
        fontSize=min(26.0, b + 14),
        alignment=TA_LEFT,
        spaceAfter=10,
        fontName="Helvetica-Bold",
        textColor=primary_color,
    )

    style_section_heading = ParagraphStyle(
        name="SectionHeading",
        parent=styles["Heading2"],
        fontSize=b + 1,
        spaceBefore=12,
        spaceAfter=4,
        fontName="Helvetica-Bold",
        textColor=primary_color,
        alignment=TA_LEFT,
    )

    style_normal = ParagraphStyle(
        name="Normal",
        parent=styles["Normal"],
        fontSize=b,
        leading=b * 1.35,
        fontName="Helvetica",
        textColor=text_color,
    )

    style_contact = ParagraphStyle(
        name="Contact",
        parent=styles["Normal"],
        alignment=TA_LEFT,
        fontSize=max(8.0, b - 2),
        leading=max(10.0, b - 1),
        spaceAfter=2,
        textColor=secondary_color,
    )

    style_job_title = ParagraphStyle(
        name="JobTitle",
        parent=styles["Normal"],
        fontSize=b + 1,
        spaceAfter=4,
        fontName="Helvetica-Bold",
        textColor=primary_color,
    )

    style_company = ParagraphStyle(
        name="Company",
        parent=styles["Normal"],
        spaceBefore=2,
        fontSize=max(8.0, b - 1),
        fontName="Helvetica-Bold",
        textColor=secondary_color,
    )

    style_dates = ParagraphStyle(
        name="Dates",
        parent=styles["Normal"],
        fontSize=max(8.0, b - 2),
        alignment=TA_RIGHT,
        fontName="Helvetica-Oblique",
        textColor=light_text,
    )

    style_bullet = ParagraphStyle(
        name="Bullet",
        parent=styles["Normal"],
        fontSize=b,
        leading=b * 1.35,
        leftIndent=15,
        bulletIndent=0,
        fontName="Helvetica",
        textColor=text_color,
        spaceAfter=4,
    )

    style_tech = ParagraphStyle(
        name="Technologies",
        parent=styles["Normal"],
        fontSize=max(8.0, b - 2),
        fontName="Helvetica-Oblique",
        textColor=light_text,
        spaceAfter=8,
    )

    story = []

    if resume_data.name:
        story.append(Paragraph(resume_data.name.upper(), style_name))

    contact_info = []
    if resume_data.email and resume_data.email != "NA":
        contact_info.append(resume_data.email)
    if resume_data.phone and resume_data.phone != "NA":
        contact_info.append(resume_data.phone)
    if resume_data.location and resume_data.location != "NA":
        contact_info.append(resume_data.location)
    if contact_info:
        story.append(Paragraph(" | ".join(contact_info), style_contact))

    links = []
    if resume_data.links:

        def format_link(url, label):
            clean_url = url if url.startswith("http") else f"https://{url}"
            clean_url = clean_url.replace("&", "&amp;")
            return f'<u><a href="{clean_url}"><font color="#1976D2">{label}</font></a></u>'

        if resume_data.links.linkedin and resume_data.links.linkedin != "NA":
            links.append(format_link(resume_data.links.linkedin, "LinkedIn"))
        if resume_data.links.github and resume_data.links.github != "NA":
            links.append(format_link(resume_data.links.github, "GitHub"))
        if resume_data.links.portfolio and resume_data.links.portfolio != "NA":
            links.append(format_link(resume_data.links.portfolio, "Portfolio"))

    if links:
        story.append(Paragraph(" | ".join(links), style_contact))

    if resume_data.summary and resume_data.summary != "NA":
        story.append(Paragraph("PROFESSIONAL SUMMARY", style_section_heading))
        story.append(
            HRFlowable(
                width="100%",
                thickness=1,
                color=colors.HexColor("#2C3E50"),
                spaceBefore=0,
                spaceAfter=8,
            )
        )

        cleaned_summary = resume_data.summary
        if cleaned_summary.startswith('"') and cleaned_summary.endswith('"'):
            cleaned_summary = cleaned_summary[1:-1]

        story.append(Paragraph(cleaned_summary, style_normal))

    if resume_data.skills and resume_data.skills != ["NA"]:
        skills_list = [s for s in resume_data.skills if s != "NA"]

        if skills_list:
            story.append(Paragraph("SKILLS", style_section_heading))
            story.append(
                HRFlowable(
                    width="100%",
                    thickness=1,
                    color=colors.HexColor("#2C3E50"),
                    spaceBefore=0,
                    spaceAfter=8,
                )
            )

            num_columns = 3
            table_data = []
            num_skills = len(skills_list)
            rows = (num_skills + num_columns - 1) // num_columns

            for i in range(rows):
                row_items = []
                for j in range(num_columns):
                    skill_index = i * num_columns + j
                    if skill_index < num_skills:
                        skill_text = f"• {skills_list[skill_index]}"
                        row_items.append(Paragraph(skill_text, style_normal))
                    else:
                        row_items.append(Paragraph("", style_normal))
                table_data.append(row_items)

            if table_data:
                col_width = page_width_available / num_columns
                colWidths = [col_width] * num_columns

                skills_table = Table(table_data, colWidths=colWidths)
                skills_table.setStyle(
                    TableStyle(
                        [
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (0, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ]
                    )
                )
                story.append(skills_table)
                story.append(Spacer(1, 0.1 * inch))

    if resume_data.experience:
        story.append(Paragraph("PROFESSIONAL EXPERIENCE", style_section_heading))
        story.append(
            HRFlowable(
                width="100%",
                thickness=1,
                color=colors.HexColor("#2C3E50"),
                spaceBefore=0,
                spaceAfter=8,
            )
        )

        w_left = page_width_available * 0.62
        w_right = page_width_available * 0.38

        for exp in resume_data.experience:
            job_title = f"{exp.job_title}" if exp.job_title != "NA" else ""

            company_parts = []
            if exp.company and exp.company != "NA":
                company_parts.append(exp.company)
            if exp.location and exp.location != "NA":
                company_parts.append(exp.location)
            company_location = " | ".join(company_parts)

            dates = ""
            if exp.start_date and exp.start_date != "NA" and exp.end_date and exp.end_date != "NA":
                dates = f"{exp.start_date} - {exp.end_date}"
            elif exp.start_date and exp.start_date != "NA":
                dates = f"{exp.start_date} - Present"

            data = [[Paragraph(job_title, style_job_title), Paragraph(dates, style_dates)]]
            tbl = Table(data, colWidths=[w_left, w_right])
            tbl.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                        ("LEFTPADDING", (0, 0), (0, -1), 0),
                    ]
                )
            )
            story.append(tbl)

            story.append(Paragraph(company_location, style_company))
            story.append(Spacer(1, 0.1 * inch))

            if exp.description and exp.description != "NA":
                if "\n" in exp.description:
                    bullets = exp.description.split("\n")
                    for bullet in bullets:
                        if bullet.strip():
                            bullet_text = bullet.strip()
                            if not bullet_text.startswith("-") and not bullet_text.startswith("•"):
                                bullet_text = f"• {bullet_text}"
                            elif bullet_text.startswith("-"):
                                bullet_text = f"• {bullet_text[1:].strip()}"

                            story.append(Paragraph(bullet_text, style_bullet))
                else:
                    text = exp.description.strip()

                    text = text.replace("e.g.", "TEMP_EG")
                    text = text.replace("i.e.", "TEMP_IE")
                    text = text.replace("etc.", "TEMP_ETC")
                    text = text.replace("vs.", "TEMP_VS")
                    text = text.replace("Mr.", "TEMP_MR")
                    text = text.replace("Mrs.", "TEMP_MRS")
                    text = text.replace("Ms.", "TEMP_MS")
                    text = text.replace("Dr.", "TEMP_DR")
                    text = text.replace("St.", "TEMP_ST")
                    text = text.replace("Ph.D.", "TEMP_PHD")
                    text = text.replace("U.S.", "TEMP_US")
                    text = text.replace("U.K.", "TEMP_UK")

                    sentences = text.split(". ")

                    for i, sentence in enumerate(sentences):
                        if sentence:
                            sentence = sentence.replace("TEMP_EG", "e.g.")
                            sentence = sentence.replace("TEMP_IE", "i.e.")
                            sentence = sentence.replace("TEMP_ETC", "etc.")
                            sentence = sentence.replace("TEMP_VS", "vs.")
                            sentence = sentence.replace("TEMP_MR", "Mr.")
                            sentence = sentence.replace("TEMP_MRS", "Mrs.")
                            sentence = sentence.replace("TEMP_MS", "Ms.")
                            sentence = sentence.replace("TEMP_DR", "Dr.")
                            sentence = sentence.replace("TEMP_ST", "St.")
                            sentence = sentence.replace("TEMP_PHD", "Ph.D.")
                            sentence = sentence.replace("TEMP_US", "U.S.")
                            sentence = sentence.replace("TEMP_UK", "U.K.")

                            if i < len(sentences) - 1 or not sentence[-1] in [".", "!", "?"]:
                                sentence = sentence + "."

                            story.append(Paragraph(f"• {sentence.strip()}", style_bullet))

            story.append(Spacer(1, 0.15 * inch))

    if resume_data.education:
        story.append(Paragraph("EDUCATION", style_section_heading))
        story.append(
            HRFlowable(
                width="100%",
                thickness=1,
                color=colors.HexColor("#2C3E50"),
                spaceBefore=0,
                spaceAfter=8,
            )
        )

        ew_left = page_width_available * 0.72
        ew_right = page_width_available * 0.28

        for edu in resume_data.education:
            degree_info = f"<b>{edu.degree}</b>" if edu.degree != "NA" else ""
            if edu.field_of_study and edu.field_of_study != "NA":
                degree_info += f", {edu.field_of_study}"

            years = ""
            if edu.start_year and edu.start_year != "NA" and edu.end_year and edu.end_year != "NA":
                years = f"{edu.start_year} - {edu.end_year}"
            elif edu.start_year and edu.start_year != "NA":
                years = f"Started {edu.start_year}"
            elif edu.end_year and edu.end_year != "NA":
                years = f"Graduated {edu.end_year}"

            data = [[Paragraph(degree_info, style_normal), Paragraph(years, style_dates)]]
            tbl = Table(data, colWidths=[ew_left, ew_right])
            tbl.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (0, -1), 0),
                    ]
                )
            )
            story.append(tbl)

            if edu.institution and edu.institution != "NA":
                story.append(Paragraph(edu.institution, style_normal))
            story.append(Spacer(1, 0.15 * inch))

    if resume_data.projects:
        story.append(Paragraph("PROJECTS", style_section_heading))
        story.append(
            HRFlowable(
                width="100%",
                thickness=1,
                color=colors.HexColor("#2C3E50"),
                spaceBefore=0,
                spaceAfter=8,
            )
        )

        for proj in resume_data.projects:
            if proj.name and proj.name != "NA":
                story.append(Paragraph(f"<b>{proj.name}</b>", style_job_title))

            if proj.description and proj.description != "NA":
                if "\n" in proj.description:
                    bullets = proj.description.split("\n")
                    for bullet in bullets:
                        if bullet.strip():
                            bullet_text = bullet.strip()
                            if not bullet_text.startswith("-") and not bullet_text.startswith("•"):
                                bullet_text = f"• {bullet_text}"
                            elif bullet_text.startswith("-"):
                                bullet_text = f"• {bullet_text[1:].strip()}"
                            story.append(Paragraph(bullet_text, style_bullet))
                else:
                    text = proj.description.strip()

                    text = text.replace("e.g.", "TEMP_EG")
                    text = text.replace("i.e.", "TEMP_IE")
                    text = text.replace("etc.", "TEMP_ETC")
                    text = text.replace("vs.", "TEMP_VS")
                    text = text.replace("Mr.", "TEMP_MR")
                    text = text.replace("Mrs.", "TEMP_MRS")
                    text = text.replace("Ms.", "TEMP_MS")
                    text = text.replace("Dr.", "TEMP_DR")
                    text = text.replace("St.", "TEMP_ST")
                    text = text.replace("Ph.D.", "TEMP_PHD")
                    text = text.replace("U.S.", "TEMP_US")
                    text = text.replace("U.K.", "TEMP_UK")

                    sentences = []
                    current_sentence = ""
                    for char in text:
                        current_sentence += char
                        if char == ".":
                            if text.index(current_sentence) + len(current_sentence) == len(text) or (
                                text.index(current_sentence) + len(current_sentence) < len(text)
                                and text[text.index(current_sentence) + len(current_sentence)] == " "
                            ):
                                sentences.append(current_sentence.strip())
                                current_sentence = ""
                    if current_sentence.strip():
                        sentences.append(current_sentence.strip())

                    if not sentences or (len(sentences) == 1 and sentences[0] == text):
                        sentences = [s.strip() for s in text.split(".") if s.strip()]
                        for i in range(len(sentences)):
                            if i < len(sentences) - 1:
                                sentences[i] = sentences[i] + "."
                            elif not sentences[i].endswith((".", "!", "?")):
                                sentences[i] = sentences[i] + "."

                    for sentence in sentences:
                        if sentence:
                            sentence = sentence.replace("TEMP_EG", "e.g.")
                            sentence = sentence.replace("TEMP_IE", "i.e.")
                            sentence = sentence.replace("TEMP_ETC", "etc.")
                            sentence = sentence.replace("TEMP_VS", "vs.")
                            sentence = sentence.replace("TEMP_MR", "Mr.")
                            sentence = sentence.replace("TEMP_MRS", "Mrs.")
                            sentence = sentence.replace("TEMP_MS", "Ms.")
                            sentence = sentence.replace("TEMP_DR", "Dr.")
                            sentence = sentence.replace("TEMP_ST", "St.")
                            sentence = sentence.replace("TEMP_PHD", "Ph.D.")
                            sentence = sentence.replace("TEMP_US", "U.S.")
                            sentence = sentence.replace("TEMP_UK", "U.K.")

                            if not sentence.endswith((".", "!", "?")):
                                sentence += "."

                            story.append(Paragraph(f"• {sentence.strip()}", style_bullet))

            if proj.technologies and proj.technologies != ["NA"]:
                tech_list = [t for t in proj.technologies if t != "NA"]
                if tech_list:
                    tech_text = f"<i>Technologies:</i> {', '.join(tech_list)}"
                    story.append(Paragraph(tech_text, style_tech))

            story.append(Spacer(1, 0.15 * inch))

    if resume_data.certifications:
        story.append(Paragraph("CERTIFICATIONS", style_section_heading))
        story.append(
            HRFlowable(
                width="100%",
                thickness=1,
                color=colors.HexColor("#2C3E50"),
                spaceBefore=0,
                spaceAfter=8,
            )
        )

        cw_left = page_width_available * 0.72
        cw_right = page_width_available * 0.28

        for cert in resume_data.certifications:
            if cert.name == "NA" and cert.issuer == "NA":
                continue

            cert_name = f"<b>{cert.name}</b>" if cert.name != "NA" else ""

            year_text = ""
            if cert.year and cert.year != "NA":
                year_text = cert.year

            data = [[Paragraph(cert_name, style_normal), Paragraph(year_text, style_dates)]]
            tbl = Table(data, colWidths=[cw_left, cw_right])
            tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(tbl)

            if cert.issuer and cert.issuer != "NA":
                story.append(Paragraph(cert.issuer, style_normal))

            story.append(Spacer(1, 0.1 * inch))

    if resume_data.languages and resume_data.languages != ["NA"]:
        lang_list = [l for l in resume_data.languages if l != "NA"]
        if lang_list:
            story.append(Paragraph("LANGUAGES", style_section_heading))
            story.append(
                HRFlowable(
                    width="100%",
                    thickness=1,
                    color=colors.HexColor("#2C3E50"),
                    spaceBefore=0,
                    spaceAfter=8,
                )
            )
            story.append(Paragraph(", ".join(lang_list), style_normal))

    try:
        doc.build(story)
        logging.info("PDF built at base font %spt.", base_font_pt)
    except Exception as e:
        logging.error("Error building PDF: %s", e)
        raise

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def create_resume_pdf(resume_data: Resume) -> bytes:
    """
    A4 resume PDF: try 11pt body; if more than 2 pages, retry at 10pt.
    If still over 2 pages, log a warning but return the PDF.
    """
    pdf_bytes = _build_resume_pdf_bytes(resume_data, 11.0)
    n = _pdf_page_count(pdf_bytes)
    if n > 2:
        logging.info("PDF has %s pages at 11pt; retrying at 10pt.", n)
        pdf_bytes = _build_resume_pdf_bytes(resume_data, 10.0)
        n2 = _pdf_page_count(pdf_bytes)
        if n2 > 2:
            logging.warning(
                "Resume PDF still has %s pages after reducing base font to 10pt (target max 2 pages A4).",
                n2,
            )
    return pdf_bytes


def _row_to_resume(row: dict) -> Resume:
    """Map a customized_resumes DB row into a Resume model."""
    links_raw = row.get("links") or {}
    if isinstance(links_raw, dict):
        links = Links(**links_raw)
    else:
        links = Links()

    payload = {
        "name": row.get("name") or "",
        "email": row.get("email") or "",
        "phone": row.get("phone") or "",
        "location": row.get("location") or "",
        "summary": row.get("summary") or "",
        "skills": row.get("skills") or [],
        "education": row.get("education") or [],
        "experience": row.get("experience") or [],
        "projects": row.get("projects") or [],
        "certifications": row.get("certifications") or [],
        "languages": row.get("languages") or [],
        "links": links,
    }
    return Resume.model_validate(payload)


def generate_pdf_for_job_id(job_id: str) -> Optional[str]:
    """
    Load customized resume for job, render PDF, upload to storage, set resume_link.
    Returns storage path on success.
    """
    import config
    import supabase_utils

    job = (
        supabase_utils.supabase.table(config.SUPABASE_TABLE_NAME)
        .select("customized_resume_id")
        .eq(config.SUPABASE_JOB_PK_COL, job_id)
        .limit(1)
        .execute()
    )
    if not job.data:
        logging.error("Job not found: %s", job_id)
        return None
    rid = job.data[0].get("customized_resume_id")
    if not rid:
        logging.error("Job %s has no customized_resume_id; run custom_resume_generator first.", job_id)
        return None

    row = supabase_utils.get_customized_resume(str(rid))
    if not row:
        logging.error("Customized resume row not found: %s", rid)
        return None

    resume_model = _row_to_resume(row)
    pdf_bytes = create_resume_pdf(resume_model)
    destination_path = f"resume_{job_id}.pdf"
    path = supabase_utils.upload_customized_resume_to_storage(pdf_bytes, destination_path)
    if not path:
        return None
    supabase_utils.update_customized_resume_link(str(rid), path)
    return path


if __name__ == "__main__":
    import config as _cfg

    if len(sys.argv) < 2:
        logging.error("Usage: python pdf_generator.py <job_id>")
        sys.exit(1)
    jid = sys.argv[1].strip()
    if not _cfg.SUPABASE_URL or not _cfg.SUPABASE_SERVICE_ROLE_KEY:
        logging.error("Supabase environment not configured.")
        sys.exit(1)
    out = generate_pdf_for_job_id(jid)
    if out:
        logging.info("PDF uploaded to %s", out)
    else:
        sys.exit(1)
