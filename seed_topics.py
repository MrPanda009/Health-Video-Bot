"""
Seed 120+ PubMed-appropriate research topics for the Hindi health channel.
Target demographic: Hindi-speaking adults 35-65 managing chronic conditions in India.

Editorial topic areas (from niche_profile.json):
  - chronic_disease (diabetes, hypertension, heart disease)
  - nutrition_and_diet
  - mental_health_and_sleep
  - fitness_and_exercise
  - gut_health_and_immunity
  - womens_health
  - aging_and_longevity

Run:  python seed_topics.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_db import StudyDB

TOPICS = [
    # ── Diabetes & Metabolic Health ───────────────────────────────────────────
    "type 2 diabetes exercise intervention India",
    "insulin resistance diet low glycemic index RCT",
    "prediabetes lifestyle intervention randomized trial",
    "diabetes self-management education South Asia",
    "glycemic index Indian foods diabetes control",
    "visceral fat reduction diabetes risk intervention",
    "postprandial blood glucose exercise timing study",
    "fasting mimicking diet insulin sensitivity RCT",
    "diabetes remission very low calorie diet trial",
    "HbA1c reduction dietary intervention meta-analysis",
    "diabetic neuropathy prevention lifestyle intervention",
    "gestational diabetes diet management outcomes",
    "type 2 diabetes sleep deprivation insulin resistance",
    "diabetes mindfulness stress reduction RCT",
    "sarcopenic obesity diabetes older adults intervention",
    "low carbohydrate diet type 2 diabetes India",
    "diabetes prevention program South Asian adaptation",
    "blood sugar control spice supplementation RCT",
    "diabetes complications cardiovascular prevention India",
    "metformin versus lifestyle intervention glucose control",

    # ── Hypertension & Cardiovascular ─────────────────────────────────────────
    "DASH diet hypertension randomized controlled trial",
    "blood pressure reduction potassium dietary intake",
    "cardiovascular disease risk factors South Asian adults",
    "heart failure prevention physical activity intervention",
    "stroke prevention lifestyle modification India",
    "LDL cholesterol reduction plant-based diet",
    "triglycerides reduction omega-3 exercise intervention",
    "arterial stiffness aging lifestyle modification RCT",
    "endothelial function nutrition intervention adults",
    "blood pressure sodium reduction randomized trial",
    "hypertension mindfulness meditation RCT India",
    "homocysteine cardiovascular risk B vitamins intervention",
    "C-reactive protein inflammation diet intervention",
    "coronary artery disease secondary prevention diet",
    "atrial fibrillation prevention lifestyle factors",
    "cardiovascular risk Mediterranean diet South Asia adaptation",
    "HDL cholesterol aerobic exercise intervention",
    "hypertension prevalence rural urban India comparison",
    "blood pressure yoga intervention systematic review",
    "peripheral artery disease walking exercise therapy",

    # ── Nutrition & Diet ──────────────────────────────────────────────────────
    "Mediterranean diet adaptation Indian population health",
    "plant-based diet health outcomes Indian adults",
    "turmeric curcumin anti-inflammatory randomized trial",
    "vitamin D deficiency supplementation India adults",
    "iron deficiency anemia women India dietary intervention",
    "calcium supplementation bone density adults India",
    "omega-3 supplementation cardiovascular outcomes meta-analysis",
    "ultra-processed food consumption health outcomes India",
    "dietary fiber intake metabolic health intervention",
    "antioxidant rich diet aging oxidative stress intervention",
    "zinc supplementation immune function deficiency India",
    "magnesium supplementation sleep quality blood pressure",
    "green tea polyphenols metabolic health RCT",
    "probiotics supplementation immunity digestive health India",
    "caloric restriction longevity biomarkers human trial",
    "time-restricted eating weight loss Indian adults",
    "traditional Indian fermented foods gut health",
    "spice consumption anti-inflammatory cardiovascular benefit",
    "protein quality plant animal aging muscle mass",
    "sodium intake processed food hypertension India",
    "vitamin B12 deficiency vegetarian diet India adults",
    "folic acid homocysteine cardiovascular intervention",
    "Indian traditional diet cardiovascular protection cohort",
    "diet quality score chronic disease prevention India",
    "food insecurity nutrition chronic disease India",

    # ── Mental Health & Sleep ─────────────────────────────────────────────────
    "depression lifestyle intervention middle-aged adults India",
    "anxiety mindfulness cognitive behavioral therapy RCT",
    "sleep apnea weight loss intervention outcomes",
    "insomnia cognitive behavioral therapy randomized trial",
    "workplace stress management intervention India",
    "loneliness social isolation health aging outcomes",
    "dementia prevention lifestyle modification India cohort",
    "cognitive decline diet intervention older adults",
    "anxiety omega-3 supplementation randomized trial",
    "depression exercise intervention randomized controlled trial",
    "sleep quality melatonin supplementation aging adults",
    "chronic stress cortisol reduction mindfulness intervention",
    "mental wellbeing gratitude practice intervention RCT",
    "psychological resilience physical activity aging adults",
    "burnout prevalence healthcare workers India intervention",
    "sleep duration cardiovascular risk India cohort",
    "anxiety depression comorbidity diabetes India",
    "meditation cortisol inflammatory markers RCT",
    "sleep quality gut microbiome bidirectional relationship",
    "seasonal affective disorder vitamin D intervention",

    # ── Physical Activity & Fitness ───────────────────────────────────────────
    "walking intervention type 2 diabetes prevention India",
    "resistance training older adults muscle mass preservation",
    "HIIT versus moderate continuous exercise metabolic health",
    "sedentary behavior reduction intervention chronic disease",
    "balance training fall prevention older adults RCT",
    "aerobic exercise cognitive function aging randomized trial",
    "strength training bone mineral density osteoporosis",
    "physical inactivity chronic disease mortality India",
    "low back pain exercise therapy randomized controlled trial",
    "knee osteoarthritis exercise intervention pain function",
    "exercise timing morning versus evening glycemic control",
    "sitting time cardiovascular risk reduction breaks",
    "swimming water exercise joint pain older adults",
    "occupational physical activity health outcomes India",
    "exercise prescription chronic kidney disease outcomes",
    "physical activity depression anxiety intervention meta-analysis",
    "yoga metabolic syndrome randomized controlled trial India",
    "exercise immune function aging older adults",
    "physical activity non-alcoholic fatty liver disease",
    "step count cardiovascular mortality cohort study",

    # ── Gut Health & Immunity ─────────────────────────────────────────────────
    "gut microbiome type 2 diabetes composition intervention",
    "irritable bowel syndrome low FODMAP diet India",
    "non-alcoholic fatty liver disease diet lifestyle intervention",
    "probiotic supplementation immunity aging older adults",
    "prebiotic dietary fiber gut health immune function",
    "gut microbiome depression anxiety mental health link",
    "Helicobacter pylori prevalence treatment outcomes India",
    "gut permeability leaky gut dietary intervention",
    "fermented food gut microbiome diversity RCT",
    "gut microbiome obesity weight loss intervention",
    "inflammatory bowel disease nutrition India management",
    "colon cancer prevention dietary fiber cruciferous vegetables",
    "gut microbiome cardiovascular disease risk cohort",
    "autoimmune disease gut microbiome diet intervention",
    "immunity vitamin C D zinc supplementation infection",

    # ── Women's Health ────────────────────────────────────────────────────────
    "PCOS polycystic ovary syndrome lifestyle diet exercise intervention",
    "menopause bone density calcium vitamin D supplementation",
    "breast cancer prevention lifestyle nutrition India",
    "polycystic ovary syndrome insulin resistance low glycemic diet",
    "menopause hot flashes phytoestrogen soy intervention RCT",
    "thyroid hypothyroidism nutrition iodine India",
    "endometriosis anti-inflammatory diet pain intervention",
    "postmenopausal osteoporosis prevention exercise intervention",
    "iron deficiency anemia pregnancy nutrition India outcomes",
    "cervical cancer risk reduction nutrition immunity India",
    "menopause cardiovascular risk hormone lifestyle intervention",
    "female infertility diet antioxidant intervention",
    "premenstrual syndrome magnesium calcium dietary intervention",
    "uterine fibroids diet lifestyle management",
    "menopause cognitive function hormone lifestyle",

    # ── Aging & Longevity ─────────────────────────────────────────────────────
    "sarcopenia muscle loss prevention nutrition exercise aging",
    "frailty prevention intervention older adults randomized trial",
    "cognitive aging brain health nutrition intervention",
    "healthy aging lifestyle factors longevity cohort India",
    "age-related macular degeneration antioxidant nutrition",
    "biological aging telomere length lifestyle factors",
    "aging immune function nutrition supplementation",
    "chronic kidney disease progression lifestyle nutrition India",
    "falls prevention older adults multifactorial intervention",
    "polypharmacy adverse effects older adults India",
    "cataract prevention nutrition antioxidant intervention",
    "oral health systemic disease aging India",
    "hearing loss prevention nutrition aging adults",
    "skin aging collagen nutrition supplementation",
    "longevity centenarian lifestyle diet physical activity",
]


def main():
    db = StudyDB()
    added = 0
    skipped = 0
    for name in TOPICS:
        try:
            db.add_topic(name)
            added += 1
            print(f"  + {name}")
        except ValueError:
            skipped += 1

    stats = db.get_topic_stats()
    print(f"\n{'='*60}")
    print(f"  Added:   {added}")
    print(f"  Skipped: {skipped} (already exist)")
    print(f"  Total active topics in DB: {stats['total_active']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
