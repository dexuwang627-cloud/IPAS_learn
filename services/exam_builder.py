from weasyprint import HTML
from jinja2 import Environment, FileSystemLoader
from datetime import date
import os


def build_exam_pdf(questions: list[dict], include_answers: bool = False) -> bytes:
    choice_qs = [q for q in questions if q["type"] == "choice"]
    tf_qs = [q for q in questions if q["type"] == "truefalse"]
    chapters = list({q["chapter"] for q in questions})

    template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("exam_template.html")

    html_content = template.render(
        choice_questions=choice_qs,
        tf_questions=tf_qs,
        chapters="、".join(chapters),
        total=len(questions),
        date=date.today().strftime("%Y-%m-%d"),
        include_answers=include_answers
    )

    return HTML(string=html_content).write_pdf()
