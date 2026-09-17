# -*- coding: utf-8 -*-
import re
import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class SurveyQuestion(models.Model):
    _inherit = 'survey.question'

    question_weight = fields.Float(
        string="Weight",
        default=1.0,
        digits=(16, 2),
        help="Weight of this question in appraisal 360 evaluation scoring (e.g. 1.0, 0.75, 2.0)."
    )
    max_score = fields.Float(
        string="Max Score",
        default=5.0,
        digits=(16, 2),
        help="Maximum possible score for this question (defaults to 5.0 for standard 1 to 5 scale)."
    )
    is_weighted = fields.Boolean(
        string="Include in Evaluation",
        compute="_compute_is_weighted",
        store=True,
        readonly=False,
        help="Whether this question participates in the weighted appraisal score calculation."
    )

    @api.depends('question_type')
    def _compute_is_weighted(self):
        for question in self:
            # Questions with scored choices, matrix, or numeric rating scales default to True
            if question.question_type in ['simple_choice', 'multiple_choice', 'matrix', 'scale', 'numerical_box']:
                question.is_weighted = True
            else:
                # Open text, dates, char box questions default to False so they do not dilute numeric scoring
                question.is_weighted = False


class SurveyUserInputLine(models.Model):
    _inherit = 'survey.user_input.line'

    raw_score = fields.Float(
        string="Answer Score",
        compute="_compute_raw_and_weighted_score",
        store=True,
        digits=(16, 2),
        help="The numeric score of this answer (e.g., 1.0 to 5.0)."
    )
    question_weight = fields.Float(
        string="Question Weight",
        related="question_id.question_weight",
        store=True,
        digits=(16, 2),
    )
    weighted_score = fields.Float(
        string="Weighted Score",
        compute="_compute_raw_and_weighted_score",
        store=True,
        digits=(16, 2),
        help="Calculated as Answer Score * Question Weight."
    )

    @api.depends(
        'answer_type',
        'suggested_answer_id',
        'suggested_answer_id.answer_score',
        'suggested_answer_id.value',
        'value_scale',
        'value_numerical_box',
        'answer_score',
        'question_id',
        'question_id.question_weight',
        'question_id.is_weighted',
        'skipped'
    )
    def _compute_raw_and_weighted_score(self):
        for line in self:
            if line.skipped or not line.question_id or not line.question_id.is_weighted:
                line.raw_score = 0.0
                line.weighted_score = 0.0
                continue

            score = 0.0
            # 1. Check suggested answer (simple_choice, multiple_choice, matrix column)
            if line.suggested_answer_id:
                if line.suggested_answer_id.answer_score > 0:
                    score = line.suggested_answer_id.answer_score
                elif line.suggested_answer_id.value:
                    # Extract leading float/integer from label (e.g. '1', '2.5', '5', '4 - Very Good')
                    val_str = str(line.suggested_answer_id.value).strip()
                    m = re.match(r'^([0-9]+(?:\.[0-9]+)?)', val_str)
                    if m:
                        try:
                            score = float(m.group(1))
                        except (ValueError, TypeError):
                            score = 0.0
            # 2. Scale question (e.g. 1 to 5)
            elif line.answer_type == 'scale' and line.value_scale:
                score = float(line.value_scale)
            # 3. Numerical box question
            elif line.answer_type == 'numerical_box' and line.value_numerical_box is not False:
                score = float(line.value_numerical_box or 0.0)
            # 4. Fallback to answer_score if already populated
            elif line.answer_score and line.answer_score > 0:
                score = line.answer_score

            weight = line.question_id.question_weight if line.question_id.question_weight else 0.0
            line.raw_score = round(score, 2)
            line.weighted_score = round(score * weight, 2)


class SurveyUserInput(models.Model):
    _inherit = 'survey.user_input'

    total_weight = fields.Float(
        string="Total Weight",
        compute="_compute_weighted_evaluation",
        store=True,
        digits=(16, 2),
        help="Sum of weights of all answered scored questions."
    )
    final_weighted_score = fields.Float(
        string="Final Weighted Score",
        compute="_compute_weighted_evaluation",
        store=True,
        digits=(16, 2),
        help="Final weighted average score (scale 1.0 - 5.0)."
    )
    final_score_percentage = fields.Float(
        string="Final Score (%)",
        compute="_compute_weighted_evaluation",
        store=True,
        digits=(16, 2),
        help="Final weighted score expressed as a percentage of maximum possible points."
    )
    max_possible_weighted_score = fields.Float(
        string="Max Possible Weighted Score",
        compute="_compute_weighted_evaluation",
        store=True,
        digits=(16, 2),
    )

    @api.depends(
        'user_input_line_ids.raw_score',
        'user_input_line_ids.weighted_score',
        'user_input_line_ids.question_id',
        'user_input_line_ids.question_id.question_weight',
        'user_input_line_ids.question_id.max_score',
        'user_input_line_ids.question_id.is_weighted',
        'user_input_line_ids.skipped',
        'state'
    )
    def _compute_weighted_evaluation(self):
        for user_input in self:
            # Filter lines that belong to an answered, weighted question
            scored_lines = user_input.user_input_line_ids.filtered(
                lambda l: not l.skipped and l.question_id and l.question_id.is_weighted and l.question_id.question_weight > 0
            )

            # Group lines by question to correctly balance matrix questions (multi-row) with single questions
            question_scores = {}
            for line in scored_lines:
                q = line.question_id
                if q not in question_scores:
                    question_scores[q] = []
                question_scores[q].append(line.raw_score)

            total_weighted_points = 0.0
            total_max_weighted_points = 0.0
            total_weight = 0.0

            for q, scores in question_scores.items():
                if not scores:
                    continue
                # Average score across all answered rows/items for this question
                avg_q_score = sum(scores) / len(scores)
                q_weight = q.question_weight
                q_max = q.max_score if q.max_score > 0 else 5.0

                total_weighted_points += avg_q_score * q_weight
                total_max_weighted_points += q_max * q_weight
                total_weight += q_weight

            user_input.total_weight = round(total_weight, 2)
            user_input.max_possible_weighted_score = round(total_max_weighted_points, 2)

            if total_weight > 0:
                user_input.final_weighted_score = round(total_weighted_points / total_weight, 2)
            else:
                user_input.final_weighted_score = 0.0

            if total_max_weighted_points > 0:
                user_input.final_score_percentage = round((total_weighted_points / total_max_weighted_points) * 100.0, 2)
            else:
                user_input.final_score_percentage = 0.0


class HrAppraisal(models.Model):
    _inherit = 'hr.appraisal'

    survey_input_ids = fields.One2many(
        'survey.user_input',
        'appraisal_id',
        string="Feedback Surveys"
    )
    final_360_score = fields.Float(
        string="360 Evaluation Score",
        compute="_compute_360_final_scores",
        store=True,
        digits=(16, 2),
        help="Overall weighted evaluation score across completed 360 feedback surveys (scale 1.0 - 5.0)."
    )
    final_360_percentage = fields.Float(
        string="360 Evaluation (%)",
        compute="_compute_360_final_scores",
        store=True,
        digits=(16, 2),
        help="Overall percentage score across completed 360 feedback surveys."
    )

    @api.depends(
        'survey_input_ids.state',
        'survey_input_ids.final_weighted_score',
        'survey_input_ids.final_score_percentage',
        'survey_input_ids.total_weight'
    )
    def _compute_360_final_scores(self):
        for appraisal in self:
            completed_surveys = appraisal.survey_input_ids.filtered(
                lambda s: s.state == 'done' and s.total_weight > 0
            )
            if completed_surveys:
                total_score = sum(s.final_weighted_score for s in completed_surveys)
                total_pct = sum(s.final_score_percentage for s in completed_surveys)
                appraisal.final_360_score = round(total_score / len(completed_surveys), 2)
                appraisal.final_360_percentage = round(total_pct / len(completed_surveys), 2)
            else:
                appraisal.final_360_score = 0.0
                appraisal.final_360_percentage = 0.0
