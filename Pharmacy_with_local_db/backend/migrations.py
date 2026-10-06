"""Versioned migrations + seed data for the pharmacy database.

- Every migration is idempotent: re-running `migrate()` is always safe.
- Applied versions are recorded in the `schema_migrations` table.
- Works on fresh databases and on every historical pharmacy.db layout
  (missing tables / missing columns are backfilled).

Run at startup via migrate(engine). New change? Append a (version, name, fn).
"""

from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from models import (
    Base,
    Bill,
    Customer,
    GstRate,
    Medicine,
    PaymentMode,
    StockMovement,
    StoreSetting,
    Supplier,
    UnitType,
    User,
)

SCHEMA_VERSIONS_TABLE = "schema_migrations"


def _now():
    """Local timezone-aware timestamp (keeps wall-clock readable in the UI)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ensure_column(engine, table, column, ddl):
    cols = [c["name"] for c in inspect(engine).get_columns(table)]
    if column not in cols:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        return True
    return False


def mig_001_baseline(engine):
    Base.metadata.create_all(engine)


def mig_002_legacy_columns(engine):
    _ensure_column(engine, "medicines", "unit", "TEXT NOT NULL DEFAULT 'tablet'")
    _ensure_column(engine, "bills", "discount_percent", "REAL NOT NULL DEFAULT 0.0")
    _ensure_column(engine, "bills", "discount_amount", "REAL NOT NULL DEFAULT 0.0")
    _ensure_column(engine, "bills", "payment_mode", "TEXT NOT NULL DEFAULT 'Cash'")


def mig_003_seed_admin(engine, admin_user, admin_pass):
    from werkzeug.security import generate_password_hash

    with Session(engine) as s:
        if s.query(User).filter(User.username == admin_user).count() == 0:
            s.add(
                User(
                    username=admin_user,
                    password_hash=generate_password_hash(admin_pass),
                    is_admin=True,
                    created_at=_now(),
                )
            )
            s.commit()


def mig_004_seed_master_data(engine):
    with Session(engine) as s:
        if s.query(GstRate).count() == 0:
            for rate in [5.0, 12.0, 18.0]:
                s.add(GstRate(rate=rate, is_active=True, created_at=_now()))
        if s.query(UnitType).count() == 0:
            for name in [
                "tablet",
                "capsule",
                "bottle",
                "sachet",
                "tube",
                "strip",
                "injection",
            ]:
                s.add(UnitType(name=name, is_active=True, created_at=_now()))
        if s.query(StoreSetting).count() == 0:
            s.add(
                StoreSetting(
                    id=1,
                    name="MediCare Pharmacy",
                    tagline="Your trusted neighbourhood pharmacy",
                    address="",
                    phone="",
                    gstin="",
                    logo_path="",
                    low_stock_limit=10,
                )
            )
        s.commit()


def mig_005_store_profile(engine):
    _ensure_column(
        engine, "store_settings", "name", "TEXT NOT NULL DEFAULT 'MediCare Pharmacy'"
    )
    _ensure_column(engine, "store_settings", "tagline", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(engine, "store_settings", "address", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(engine, "store_settings", "phone", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(engine, "store_settings", "gstin", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(engine, "store_settings", "logo_path", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(
        engine, "store_settings", "low_stock_limit", "INTEGER NOT NULL DEFAULT 10"
    )


def mig_006_payment_modes(engine):
    _ensure_column(engine, "payment_modes", "name", "TEXT NOT NULL DEFAULT ''")
    with Session(engine) as s:
        if s.query(PaymentMode).count() == 0:
            for name in ["Cash", "UPI", "Card", "Credit", "Other"]:
                s.add(PaymentMode(name=name, is_active=True, created_at=_now()))
            s.commit()


def mig_007_composition(engine):
    _ensure_column(engine, "medicines", "composition", "TEXT NOT NULL DEFAULT ''")
    with Session(engine) as s:
        backfill = {
            r[0]: r[1]
            for r in s.execute(
                text("SELECT name, composition FROM medicines")
            ).fetchall()
        }
        SAMPLE_STOCK = {
            "Paracetamol 500mg Tablet": 3000,
            "Cetirizine 10mg Tablet": 1500,
            "Vitamin C Chewable Tablet": 1200,
            "ORS Powder 21.8g": 96,
            "Azithromycin 500mg Tablet": 237,
        }
        for name, comp in SAMPLE_STOCK.items():
            if name in backfill and not backfill[name]:
                s.execute(
                    text("UPDATE medicines SET composition = :c WHERE name = :n"),
                    {"c": comp, "n": name},
                )
        s.commit()


CATALOG = [
    (
        "Amoxicillin 500mg Capsule",
        "Amoxicillin Trihydrate",
        "capsule",
        "B201",
        "2027-06-30",
        500,
        8.00,
        5.0,
        "Broad-spectrum penicillin antibiotic treating bacterial infections of ear, nose, throat, skin, and urinary tract.",
        "Take with food as directed. Complete the full course even if symptoms improve. Avoid alcohol.",
    ),
    (
        "Cefixime 200mg Tablet",
        "Cefixime Trihydrate",
        "tablet",
        "B202",
        "2027-09-30",
        300,
        12.00,
        5.0,
        "Third-generation cephalosporin antibiotic for treating bacterial infections of the throat, chest, and urinary tract.",
        "Take with or without food. Complete the full course as prescribed. Do not skip doses.",
    ),
    (
        "Ciprofloxacin 500mg Tablet",
        "Ciprofloxacin Hydrochloride",
        "tablet",
        "B203",
        "2027-03-31",
        400,
        6.00,
        5.0,
        "Fluoroquinolone antibiotic prescribed for bacterial infections of the skin, lungs, kidneys, bladder, and stomach.",
        "Take with food. Avoid direct sunlight as it may cause skin sensitivity. Do not take with dairy or antacids 2 hours before or after.",
    ),
    (
        "Doxycycline 100mg Capsule",
        "Doxycycline Hyclate",
        "capsule",
        "B204",
        "2026-12-31",
        400,
        4.00,
        5.0,
        "Tetracycline antibiotic used to treat acne, urinary tract infections, respiratory infections, and certain parasitic diseases.",
        "Take with a full glass of water while sitting upright. Avoid lying down for 30 minutes after. Take with food to reduce stomach upset.",
    ),
    (
        "Metronidazole 400mg Tablet",
        "Metronidazole",
        "tablet",
        "B205",
        "2027-01-31",
        500,
        3.00,
        5.0,
        "Antibiotic and antiprotozoal used to treat infections of the stomach, skin, joints, respiratory tract, and vagina.",
        "Avoid alcohol completely during treatment and for 48 hours after — severe nausea/vomiting may occur. Take with food.",
    ),
    (
        "Paracetamol 650mg Tablet",
        "Paracetamol",
        "tablet",
        "B206",
        "2028-02-29",
        3000,
        2.50,
        5.0,
        "Analgesic and antipyretic used for fever, headache, muscle aches, and mild to moderate pain relief.",
        "Take with or without food. Do not exceed 4g/day (adults). Avoid alcohol to prevent liver damage. Consult doctor if fever persists beyond 3 days.",
    ),
    (
        "Ibuprofen 400mg Tablet",
        "Ibuprofen",
        "tablet",
        "B207",
        "2027-07-31",
        1500,
        3.00,
        5.0,
        "NSAID used for pain, inflammation, fever, and conditions like arthritis, menstrual cramps, and headache.",
        "Take with food or milk to prevent stomach upset. Avoid in pregnancy (third trimester). Do not exceed recommended dose.",
    ),
    (
        "Diclofenac 50mg Tablet",
        "Diclofenac Sodium",
        "tablet",
        "B208",
        "2027-05-31",
        1000,
        2.50,
        5.0,
        "NSAID prescribed for pain and inflammation in conditions such as arthritis, sprains, and menstrual pain.",
        "Take with food to reduce stomach irritation. Avoid if you have a history of stomach ulcers or heart disease.",
    ),
    (
        "Ecosprin 75mg Tablet",
        "Aspirin",
        "tablet",
        "B209",
        "2028-01-31",
        1000,
        1.50,
        5.0,
        "Low-dose aspirin used for cardiovascular protection — preventing heart attacks and strokes in at-risk patients.",
        "Take as directed by doctor, usually once daily with food. Do not stop abruptly. Notify doctor before surgery.",
    ),
    (
        "Omeprazole 20mg Capsule",
        "Omeprazole",
        "capsule",
        "B210",
        "2027-04-30",
        800,
        4.00,
        5.0,
        "Proton pump inhibitor used to treat acid reflux, heartburn, GERD, stomach ulcers, and Zollinger-Ellison syndrome.",
        "Take 30 minutes before breakfast on an empty stomach. Complete the full course even if symptoms improve.",
    ),
    (
        "Pantoprazole 40mg Tablet",
        "Pantoprazole Sodium",
        "tablet",
        "B211",
        "2027-08-31",
        800,
        7.00,
        5.0,
        "Proton pump inhibitor used for GERD, erosive esophagitis, and pathologies causing excess stomach acid production.",
        "Take one hour before breakfast. Swallow whole — do not crush or chew. Long-term use requires periodic medical review.",
    ),
    (
        "Famotidine 20mg Tablet",
        "Famotidine",
        "tablet",
        "B212",
        "2027-02-28",
        500,
        3.00,
        5.0,
        "H2 blocker that reduces stomach acid production — used for ulcers, GERD, and heartburn.",
        "Take at bedtime or as directed. May be taken with or without food. Reduce dose if kidney impairment.",
    ),
    (
        "Domperidone 10mg Tablet",
        "Domperidone",
        "tablet",
        "B213",
        "2026-11-30",
        600,
        4.00,
        5.0,
        "Anti-emetic and prokinetic used for nausea, vomiting, bloating, and gastric motility disorders.",
        "Take 15-30 minutes before meals. Avoid if you have heart conditions or electrolyte imbalances.",
    ),
    (
        "Antacid Chewable Tablet",
        "Dried Aluminium Hydroxide + Magnesium Hydroxide",
        "tablet",
        "B214",
        "2027-10-31",
        600,
        5.00,
        5.0,
        "Combination antacid providing rapid relief from acidity, heartburn, indigestion, and stomach upset.",
        "Chew thoroughly before swallowing. Take after meals or at symptom onset. Do not take with other medicines within 2 hours.",
    ),
    (
        "Loperamide 2mg Tablet",
        "Loperamide Hydrochloride",
        "tablet",
        "B215",
        "2027-06-30",
        300,
        4.00,
        5.0,
        "Anti-diarrheal that slows gut motility — used for acute and chronic diarrhea management.",
        "Use only as directed. Discontinue if diarrhea worsens or blood/mucus appears in stool. Not for children under 6 without advice.",
    ),
    (
        "Albendazole 400mg Tablet",
        "Albendazole",
        "tablet",
        "B216",
        "2027-12-31",
        300,
        12.00,
        5.0,
        "Antiparasitic used to treat infections caused by worms such as roundworm, hookworm, tapeworm, and hydatid disease.",
        "Take with a fatty meal to enhance absorption. Regular deworming recommended in endemic areas.",
    ),
    (
        "Levocetirizine 5mg Tablet",
        "Levocetirizine Dihydrochloride",
        "tablet",
        "B217",
        "2027-09-30",
        800,
        4.00,
        5.0,
        "Third-generation antihistamine for allergic rhinitis, chronic urticaria, and other allergic conditions.",
        "May cause mild drowsiness — avoid driving or operating machinery until response is known. Take once daily.",
    ),
    (
        "Loratadine 10mg Tablet",
        "Loratadine",
        "tablet",
        "B218",
        "2027-05-31",
        500,
        3.00,
        5.0,
        "Second-generation antihistamine for allergies — runny nose, sneezing, itchy eyes, and allergic skin reactions.",
        "Non-drowsy formula — safe for daily use. Take once daily, with or without food.",
    ),
    (
        "Cough Relief Syrup 100ml",
        "Dextromethorphan + Chlorpheniramine",
        "bottle",
        "B219",
        "2026-10-31",
        60,
        110.00,
        12.0,
        "Combination syrup for symptomatic relief of dry cough, sneezing, and runny nose associated with common cold.",
        "Shake well before use. Measure dose with provided cup. Avoid alcohol and driving due to sedative effect.",
    ),
    (
        "Cold Relief Tablet",
        "Paracetamol + Phenylephrine + Chlorpheniramine",
        "tablet",
        "B220",
        "2027-07-31",
        800,
        4.00,
        5.0,
        "Combination tablet for symptomatic relief of cold — fever, nasal congestion, sneezing, and runny nose.",
        "Take with food. Avoid alcohol. Not recommended for children under 12 without medical advice.",
    ),
    (
        "Ondansetron 4mg Tablet",
        "Ondansetron Hydrochloride",
        "tablet",
        "B221",
        "2027-08-31",
        500,
        5.00,
        5.0,
        "Anti-emetic used to prevent nausea and vomiting caused by chemotherapy, radiation, or postoperative conditions.",
        "Take exactly as prescribed — do not double dose if one is missed. May cause mild headache or constipation.",
    ),
    (
        "Metformin 500mg Tablet",
        "Metformin Hydrochloride",
        "tablet",
        "B222",
        "2028-03-31",
        1500,
        2.50,
        5.0,
        "Biguanide oral antidiabetic used to treat type 2 diabetes by lowering glucose production in the liver and improving insulin sensitivity.",
        "Take with food to reduce stomach upset. Monitor kidney function periodically. Never stop without consulting doctor.",
    ),
    (
        "Glimepiride 2mg Tablet",
        "Glimepiride",
        "tablet",
        "B223",
        "2027-11-30",
        800,
        4.00,
        5.0,
        "Sulfonylurea antidiabetic that stimulates insulin secretion from the pancreas for type 2 diabetes management.",
        "Take once daily with breakfast. Risk of hypoglycemia — monitor blood sugar. Avoid alcohol.",
    ),
    (
        "Amlodipine 5mg Tablet",
        "Amlodipine Besilate",
        "tablet",
        "B224",
        "2027-12-31",
        1000,
        3.00,
        5.0,
        "Calcium channel blocker prescribed for hypertension (high blood pressure) and angina (chest pain).",
        "Take once daily at the same time. Do not stop abruptly — sudden withdrawal may worsen angina. Monitor blood pressure regularly.",
    ),
    (
        "Losartan 50mg Tablet",
        "Losartan Potassium",
        "tablet",
        "B225",
        "2027-10-31",
        600,
        5.00,
        5.0,
        "Angiotensin II receptor blocker (ARB) used to treat hypertension and protect kidneys in diabetic nephropathy.",
        "Take once daily, with or without food. Monitor kidney function and electrolytes. Avoid in pregnancy.",
    ),
    (
        "Atorvastatin 10mg Tablet",
        "Atorvastatin Calcium",
        "tablet",
        "B226",
        "2027-09-30",
        600,
        6.00,
        5.0,
        "Statin prescribed to lower cholesterol and triglycerides, reducing cardiovascular disease risk.",
        "Take in the evening or at bedtime. Avoid grapefruit juice. Report unexplained muscle pain to doctor.",
    ),
    (
        "Thyroxine 50mcg Tablet",
        "Levothyroxine Sodium",
        "tablet",
        "B227",
        "2027-04-30",
        600,
        3.00,
        5.0,
        "Thyroid hormone replacement for hypothyroidism, goiter, and thyroid cancer support.",
        "Take on an empty stomach 30-60 minutes before breakfast with water. Avoid taking with calcium/iron supplements within 4 hours.",
    ),
    (
        "B-Complex Tablet",
        "B Vitamins",
        "tablet",
        "B228",
        "2027-06-30",
        800,
        3.00,
        12.0,
        "Combination of B vitamins (B1, B2, B3, B6, B12, folic acid) for energy metabolism, nerve function, and correcting deficiencies.",
        "Take with food. Supports energy levels and nervous system function. Safe for daily supplementation.",
    ),
    (
        "Calcium + Vitamin D3 Tablet",
        "Calcium Carbonate + Cholecalciferol",
        "tablet",
        "B229",
        "2027-12-31",
        600,
        6.00,
        12.0,
        "Combination supplement for bone health — prevents osteoporosis, supports calcium absorption, and treats vitamin D deficiency.",
        "Take with food for better absorption. Do not exceed recommended dose. Space calcium and thyroid medication by 4 hours.",
    ),
    (
        "Iron + Folic Acid Tablet",
        "Ferrous Ascorbate + Folic Acid",
        "tablet",
        "B230",
        "2027-08-31",
        800,
        3.00,
        12.0,
        "Supplement for iron-deficiency anemia and during pregnancy — provides essential iron and folate for red blood cell production.",
        "Take on an empty stomach for better absorption. May cause dark stools (normal). Avoid taking with tea or coffee.",
    ),
    (
        "Multivitamin Tablet",
        "Multivitamins + Minerals",
        "tablet",
        "B231",
        "2027-11-30",
        800,
        5.00,
        12.0,
        "Broad-spectrum supplement providing essential vitamins and minerals to fill nutritional gaps in daily diet.",
        "Take with a meal. Do not exceed recommended daily allowance. Not a substitute for a balanced diet.",
    ),
    (
        "Vitamin D3 60K IU Sachet",
        "Cholecalciferol",
        "sachet",
        "B232",
        "2027-05-31",
        200,
        25.00,
        12.0,
        "High-dose vitamin D supplement for deficiency — supports bone health, immunity, and calcium metabolism.",
        "Dissolve in water or milk and take once weekly. Take with food. Periodic monitoring of blood levels recommended.",
    ),
    (
        "Probiotic Sachet",
        "Saccharomyces Boulardii",
        "sachet",
        "B233",
        "2027-02-28",
        150,
        30.00,
        12.0,
        "Beneficial yeast probiotic for restoring gut flora balance, preventing/treating diarrhea, and supporting digestive health.",
        "Dissolve in cool water and consume immediately. Take at least 2 hours apart from antibiotics. Store in cool, dry place.",
    ),
    (
        "Fruit Salt Sachet 5g",
        "Sodium Bicarbonate + Citric Acid",
        "sachet",
        "B234",
        "2027-07-31",
        300,
        10.00,
        18.0,
        "Effervescent antacid for instant relief from acidity, heartburn, and indigestion.",
        "Dissolve in a glass of water and drink. Avoid if on sodium-restricted diet. Not for children under 12.",
    ),
    (
        "Antiseptic Liquid 100ml",
        "Chloroxylenol",
        "bottle",
        "B235",
        "2028-01-31",
        80,
        95.00,
        18.0,
        "Topical antiseptic liquid for cleansing wounds, cuts, abrasions, and preventing infection in minor skin injuries.",
        "Apply externally only. For external use only. Avoid contact with eyes. Keep out of reach of children.",
    ),
    (
        "Burn Cream 20g",
        "Silver Sulphadiazine",
        "tube",
        "B236",
        "2027-03-31",
        50,
        85.00,
        12.0,
        "Topical antibacterial cream for prevention and treatment of wound infection in burn wounds and skin grafts.",
        "Apply a thin layer to affected area 1-2 times daily. Clean wound before application. Use under medical supervision.",
    ),
    (
        "Diclofenac Gel 30g",
        "Diclofenac Diethylamine",
        "tube",
        "B237",
        "2027-09-30",
        60,
        90.00,
        12.0,
        "Topical NSAID gel for localized relief of pain and inflammation in muscles, joints, and soft tissue injuries.",
        "Apply to affected area and gently massage. Wash hands after application (unless treating hands). Avoid open wounds.",
    ),
    (
        "Antiseptic Ointment 20g",
        "Povidone Iodine",
        "tube",
        "B238",
        "2027-12-31",
        50,
        85.00,
        12.0,
        "Broad-spectrum topical antiseptic ointment for treating minor cuts, burns, abrasions, and preventing infection.",
        "Clean the affected area before applying. Apply a small amount and cover if needed. For external use only.",
    ),
    (
        "Sore Throat Lozenges (8)",
        "Amylmetacresol + Dichlorobenzyl Alcohol",
        "strip",
        "B239",
        "2027-06-30",
        100,
        35.00,
        12.0,
        "Antiseptic throat lozenges for symptomatic relief of sore throat, mouth ulcers, and oral infections.",
        "Suck slowly, one at a time. Do not swallow whole. Consult doctor if symptoms persist beyond 7 days.",
    ),
]

CATALOG_EXTRA = [
    (
        "Amoxicillin + Clavulanate 625mg Tablet",
        "Amoxicillin + Clavulanic Acid",
        "tablet",
        "B301",
        "2027-08-31",
        300,
        20.00,
        5.0,
        "Broad-spectrum combination antibiotic for resistant bacterial infections — sinusitis, bronchitis, urinary tract, and skin infections.",
        "Take with food to reduce stomach upset. Complete full course. Diarrhea may indicate Clostridium difficile infection.",
    ),
    (
        "Cefpodoxime 200mg Tablet",
        "Cefpodoxime Proxetil",
        "tablet",
        "B302",
        "2027-05-31",
        200,
        15.00,
        5.0,
        "Third-generation cephalosporin for treating bacterial infections including pharyngitis, tonsillitis, and uncomplicated skin infections.",
        "Take with food. Complete the full course as prescribed. Do not take with antacids containing aluminum or magnesium.",
    ),
    (
        "Ofloxacin 200mg Tablet",
        "Ofloxacin",
        "tablet",
        "B303",
        "2027-04-30",
        300,
        6.00,
        5.0,
        "Fluoroquinolone antibiotic for bacterial infections of the respiratory tract, urinary tract, skin, and eyes.",
        "Avoid sunlight and tanning beds due to photosensitivity risk. Take with food or without food.",
    ),
    (
        "Norfloxacin 400mg Tablet",
        "Norfloxacin",
        "tablet",
        "B304",
        "2027-03-31",
        300,
        5.00,
        5.0,
        "Fluoroquinolone antibiotic primarily for urinary tract infections and bacterial prostatitis.",
        "Take on an empty stomach 1 hour before or 2 hours after food. Avoid dairy and antacids 2 hours before/after.",
    ),
    (
        "Tinidazole 500mg Tablet",
        "Tinidazole",
        "tablet",
        "B305",
        "2027-06-30",
        200,
        4.00,
        5.0,
        "Antiprotozoal and antibiotic for giardiasis, amoebiasis, trichomoniasis, and bacterial vaginosis.",
        "Avoid alcohol completely during and 3 days after treatment. Take with food to reduce nausea.",
    ),
    (
        "Fluconazole 150mg Tablet",
        "Fluconazole",
        "tablet",
        "B306",
        "2027-12-31",
        150,
        20.00,
        5.0,
        "Antifungal for treating yeast infections of the mouth, throat, esophagus, and vagina.",
        "Single dose often sufficient for vaginal yeast infections. Avoid alcohol and monitor liver function with prolonged use.",
    ),
    (
        "Itraconazole 100mg Capsule",
        "Itraconazole",
        "capsule",
        "B307",
        "2027-09-30",
        150,
        15.00,
        5.0,
        "Broad-spectrum antifungal for treating fungal infections of nails, skin, lungs, and systemic mycoses.",
        "Take with a full meal for best absorption. Avoid taking with antacids or acid reducers simultaneously.",
    ),
    (
        "Ivermectin 12mg Tablet",
        "Ivermectin",
        "tablet",
        "B308",
        "2027-07-31",
        150,
        12.00,
        5.0,
        "Antiparasitic used for treating parasitic infections including scabies, river blindness, and intestinal parasites.",
        "Take on an empty stomach with water. Dose depends on condition and weight — strictly follow prescription.",
    ),
    (
        "Acyclovir 400mg Tablet",
        "Acyclovir",
        "tablet",
        "B309",
        "2027-02-28",
        150,
        10.00,
        5.0,
        "Antiviral used for herpes simplex (cold sores, genital herpes) and varicella-zoster (chickenpox, shingles).",
        "Start at first sign of outbreak. Drink plenty of water. Take with food to reduce kidney strain.",
    ),
    (
        "Aceclofenac 100mg Tablet",
        "Aceclofenac",
        "tablet",
        "B310",
        "2027-10-31",
        600,
        4.00,
        5.0,
        "NSAID prescribed for pain and inflammation in rheumatoid arthritis, osteoarthritis, ankylosing spondylitis, and acute musculoskeletal pain.",
        "Take with food. Do not use if you have active peptic ulcer or severe heart failure.",
    ),
    (
        "Aceclofenac + Paracetamol Tablet",
        "Aceclofenac + Paracetamol",
        "tablet",
        "B311",
        "2027-11-30",
        600,
        5.00,
        5.0,
        "Combination for moderate pain relief combining anti-inflammatory and analgesic effects for joint and muscular pain.",
        "Take with food. Avoid alcohol. Do not exceed 2 tablets/day without medical advice.",
    ),
    (
        "Etoricoxib 90mg Tablet",
        "Etoricoxib",
        "tablet",
        "B312",
        "2027-08-31",
        300,
        10.00,
        5.0,
        "COX-2 selective NSAID for pain and inflammation in osteoarthritis, rheumatoid arthritis, ankylosing spondylitis, and acute gout.",
        "Take with food. Not suitable for those with cardiovascular disease or peptic ulcer history.",
    ),
    (
        "Gabapentin 300mg Tablet",
        "Gabapentin",
        "tablet",
        "B313",
        "2027-06-30",
        200,
        8.00,
        5.0,
        "Anticonvulsant used for epilepsy, neuropathic pain (diabetic neuropathy, post-herpetic neuralgia), and restless legs syndrome.",
        "Take with food. Dose increased gradually as directed. Do not stop abruptly — may cause seizures.",
    ),
    (
        "Rabeprazole 20mg Tablet",
        "Rabeprazole Sodium",
        "tablet",
        "B314",
        "2027-07-31",
        500,
        6.00,
        5.0,
        "Proton pump inhibitor for GERD, peptic ulcer disease, and Helicobacter pylori eradication therapy.",
        "Take 30 minutes before breakfast. Swallow whole. Do not crush or chew.",
    ),
    (
        "Esomeprazole 40mg Tablet",
        "Esomeprazole Magnesium",
        "tablet",
        "B315",
        "2027-09-30",
        300,
        8.00,
        5.0,
        "Stereoisomer proton pump inhibitor for GERD, erosive esophagitis, and NSAID-associated ulcer prevention.",
        "Take before breakfast on an empty stomach. Not recommended for prolonged use without medical supervision.",
    ),
    (
        "Lactulose Syrup 100ml",
        "Lactulose",
        "bottle",
        "B316",
        "2026-12-31",
        40,
        110.00,
        12.0,
        "Osmotic laxative for chronic constipation, hepatic encephalopathy, and prevention of altitude sickness.",
        "Takes 24-48 hours for effect. Shake well before use. May cause bloating and gas initially.",
    ),
    (
        "Dicyclomine 10mg Tablet",
        "Dicyclomine Hydrochloride",
        "tablet",
        "B317",
        "2027-05-31",
        300,
        4.00,
        5.0,
        "Antispasmodic for relief of gastrointestinal spasm, irritable bowel syndrome, and associated abdominal cramping.",
        "Take 20 minutes before meals. Avoid if you have glaucoma, prostate enlargement, or myasthenia gravis.",
    ),
    (
        "Zinc Sulphate 20mg Tablet",
        "Zinc Sulphate",
        "tablet",
        "B318",
        "2027-08-31",
        300,
        3.00,
        12.0,
        "Zinc supplement for immune support, wound healing, skin health, and treating zinc deficiency.",
        "Take with food to reduce nausea. Avoid taking with iron supplements simultaneously. Do not exceed recommended dose.",
    ),
    (
        "Metoprolol 50mg Tablet",
        "Metoprolol Succinate",
        "tablet",
        "B319",
        "2027-10-31",
        500,
        5.00,
        5.0,
        "Beta-blocker for hypertension, angina, heart failure, and arrhythmias — reduces heart rate and blood pressure.",
        "Take once daily in the morning or as directed. Do not stop abruptly — risk of rebound hypertension.",
    ),
    (
        "Atenolol 50mg Tablet",
        "Atenolol",
        "tablet",
        "B320",
        "2027-09-30",
        400,
        3.00,
        5.0,
        "Beta-blocker for hypertension and angina — reduces heart rate and workload on the heart.",
        "Take in the morning or as directed by doctor. Monitor heart rate and blood pressure. Avoid sudden discontinuation.",
    ),
    (
        "Telmisartan 40mg Tablet",
        "Telmisartan",
        "tablet",
        "B321",
        "2027-11-30",
        500,
        6.00,
        5.0,
        "Angiotensin II receptor blocker for hypertension and cardiovascular risk reduction.",
        "Take once daily at the same time. Monitor blood pressure and kidney function. Avoid in pregnancy.",
    ),
    (
        "Olmesartan 20mg Tablet",
        "Olmesartan Medoxomil",
        "tablet",
        "B322",
        "2027-07-31",
        300,
        7.00,
        5.0,
        "ARB prescribed for hypertension — blocks angiotensin II to relax blood vessels and lower blood pressure.",
        "Take once daily, with or without food. May cause dizziness initially. Avoid in pregnancy and renal artery stenosis.",
    ),
    (
        "Clopidogrel 75mg Tablet",
        "Clopidogrel Bisulphate",
        "tablet",
        "B323",
        "2027-12-31",
        400,
        5.00,
        5.0,
        "Antiplatelet agent to prevent blood clots — used after heart attack, stent placement, stroke, and peripheral artery disease.",
        "Take at the same time daily. Do not stop without consulting doctor — risk of blood clot. Avoid NSAIDs.",
    ),
    (
        "Rosuvastatin 10mg Tablet",
        "Rosuvastatin Calcium",
        "tablet",
        "B324",
        "2027-10-31",
        400,
        7.00,
        5.0,
        "Statin for lowering LDL cholesterol and triglycerides while raising HDL — reduces cardiovascular disease risk.",
        "Take at the same time each day (usually evening). Avoid grapefruit juice. Report muscle pain or weakness.",
    ),
    (
        "Glibenclamide 5mg Tablet",
        "Glibenclamide",
        "tablet",
        "B325",
        "2027-06-30",
        400,
        2.00,
        5.0,
        "Sulfonylurea antidiabetic stimulating insulin secretion for type 2 diabetes not controlled by diet alone.",
        "Take with breakfast. Monitor blood sugar regularly. Risk of hypoglycemia — carry sugar.",
    ),
    (
        "Gliclazide 80mg Tablet",
        "Gliclazide",
        "tablet",
        "B326",
        "2027-09-30",
        400,
        4.00,
        5.0,
        "Sulfonylurea antidiabetic that promotes insulin release for type 2 diabetes management.",
        "Take with breakfast. Follow a balanced diet and regular exercise. Monitor blood glucose.",
    ),
    (
        "Voglibose 0.3mg Tablet",
        "Voglibose",
        "tablet",
        "B327",
        "2027-05-31",
        300,
        5.00,
        5.0,
        "Alpha-glucosidase inhibitor that slows carbohydrate absorption — used for type 2 diabetes to control post-meal blood sugar spikes.",
        "Take with first bite of each main meal. May cause flatulence and diarrhea initially.",
    ),
    (
        "Thyroxine 100mcg Tablet",
        "Levothyroxine Sodium",
        "tablet",
        "B328",
        "2027-08-31",
        400,
        4.00,
        5.0,
        "Higher-dose thyroid hormone replacement for hypothyroidism, large goiter, and thyroid suppression therapy.",
        "Take on an empty stomach 30-60 minutes before breakfast. Avoid calcium/iron supplements within 4 hours.",
    ),
    (
        "Amitriptyline 25mg Tablet",
        "Amitriptyline Hydrochloride",
        "tablet",
        "B329",
        "2027-07-31",
        200,
        4.00,
        5.0,
        "Tricyclic antidepressant for depression, neuropathic pain, migraine prophylaxis, and insomnia.",
        "Take at bedtime due to sedating effect. Avoid alcohol and sudden discontinuation. May cause dry mouth and drowsiness.",
    ),
    (
        "Sertraline 50mg Tablet",
        "Sertraline Hydrochloride",
        "tablet",
        "B330",
        "2027-11-30",
        200,
        7.00,
        5.0,
        "SSRI antidepressant for depression, anxiety disorders, PTSD, OCD, and panic disorder.",
        "Take in the morning or evening with food. Full therapeutic effect takes 4-6 weeks. Do not stop abruptly.",
    ),
    (
        "Escitalopram 10mg Tablet",
        "Escitalopram Oxalate",
        "tablet",
        "B331",
        "2027-12-31",
        200,
        8.00,
        5.0,
        "SSRI for depression and generalized anxiety disorder — restores serotonin balance in the brain.",
        "Take at same time daily with or without food. Avoid alcohol. May take 2-4 weeks for full effect.",
    ),
    (
        "Pregabalin 75mg Tablet",
        "Pregabalin",
        "tablet",
        "B332",
        "2027-09-30",
        200,
        8.00,
        5.0,
        "Anticonvulsant for neuropathic pain, fibromyalgia, epilepsy, and generalized anxiety disorder.",
        "Take with or without food. Dose increased gradually as directed. Risk of dizziness and drowsiness.",
    ),
    (
        "Levetiracetam 500mg Tablet",
        "Levetiracetam",
        "tablet",
        "B333",
        "2027-10-31",
        150,
        10.00,
        5.0,
        "Anticonvulsant for treating epilepsy — myoclonic seizures, partial-onset seizures, and primary generalized tonic-clonic seizures.",
        "Take with or without food at the same time daily. Do not stop without consulting doctor.",
    ),
    (
        "Montelukast 10mg Tablet",
        "Montelukast Sodium",
        "tablet",
        "B334",
        "2027-11-30",
        400,
        8.00,
        5.0,
        "Leukotriene receptor antagonist for asthma and allergic rhinitis — reduces airway inflammation and bronchoconstriction.",
        "Take in the evening for asthma. Avoid aspirin and NSAIDs if prescribed this. Report mood changes to doctor.",
    ),
    (
        "Ambroxol Syrup 100ml",
        "Ambroxol Hydrochloride",
        "bottle",
        "B335",
        "2026-11-30",
        40,
        100.00,
        12.0,
        "Mucolytic for symptomatic relief of productive cough — loosens mucus and makes it easier to cough up.",
        "Take with water after meals. Shake well before use. Do not use for more than 4-5 days without medical advice.",
    ),
    (
        "Folic Acid 5mg Tablet",
        "Folic Acid",
        "tablet",
        "B336",
        "2027-12-31",
        400,
        2.00,
        12.0,
        "Higher-dose folic acid for neural tube defect prevention in pregnancy, megaloblastic anemia, and folate deficiency.",
        "Take before conception and during pregnancy. Also used to treat folate deficiency anemia.",
    ),
    (
        "Tranexamic Acid 500mg Tablet",
        "Tranexamic Acid",
        "tablet",
        "B337",
        "2027-06-30",
        150,
        10.00,
        5.0,
        "Antifibrinolytic used to reduce heavy menstrual bleeding and for bleeding disorders during surgery.",
        "Take as directed, usually at onset of heavy bleeding. Avoid in patients with history of thrombosis.",
    ),
    (
        "Mefenamic Acid 500mg Tablet",
        "Mefenamic Acid",
        "tablet",
        "B338",
        "2027-08-31",
        300,
        5.00,
        5.0,
        "NSAID specifically indicated for primary dysmenorrhea (painful menstruation) and mild to moderate pain.",
        "Take with food at the first sign of menstrual pain. Not for prolonged use.",
    ),
    (
        "Doxylamine + B6 Tablet",
        "Doxylamine + Pyridoxine",
        "tablet",
        "B339",
        "2027-07-31",
        200,
        6.00,
        5.0,
        "Combination for relief of nausea and vomiting during pregnancy (morning sickness).",
        "Take as directed. May cause drowsiness. Consult doctor before use during pregnancy.",
    ),
    (
        "Clotrimazole Cream 30g",
        "Clotrimazole",
        "tube",
        "B340",
        "2027-04-30",
        40,
        60.00,
        12.0,
        "Topical antifungal for treating skin fungal infections — athlete's foot, ringworm, jock itch, and yeast infections.",
        "Clean and dry affected area before applying. Apply 2-3 times daily. Use for at least 2 weeks to prevent recurrence.",
    ),
    (
        "Mupirocin Ointment 5g",
        "Mupirocin",
        "tube",
        "B341",
        "2027-03-31",
        30,
        90.00,
        12.0,
        "Topical antibiotic for treating bacterial skin infections including impetigo, boils, and infected cuts.",
        "Apply a small amount to affected area 3 times daily. Do not use for more than 10 days without medical advice.",
    ),
    (
        "Permethrin Lotion 60ml",
        "Permethrin",
        "bottle",
        "B342",
        "2027-05-31",
        30,
        90.00,
        12.0,
        "Topical scabicide for treating scabies and pediculosis (head lice) — kills mites and lice on contact.",
        "Apply to damp skin from neck down, leave for 8-14 hours, then wash off. Repeat after 7 days if needed.",
    ),
    (
        "Ketoconazole Shampoo 50ml",
        "Ketoconazole",
        "bottle",
        "B343",
        "2027-02-28",
        20,
        150.00,
        18.0,
        "Antifungal shampoo for treating dandruff, seborrheic dermatitis, and pityriasis versicolor.",
        "Apply to wet hair, lather, leave for 3-5 minutes, then rinse. Use 2-3 times/week initially.",
    ),
    (
        "Ciprofloxacin Eye Drops 10ml",
        "Ciprofloxacin",
        "bottle",
        "B344",
        "2026-10-31",
        30,
        30.00,
        12.0,
        "Topical fluoroquinolone antibiotic for bacterial eye infections including conjunctivitis and corneal ulcers.",
        "Avoid touching dropper tip. Use 1-2 drops in affected eye every 2 hours initially. Do not wear contact lenses during treatment.",
    ),
    (
        "Ear Drops 10ml",
        "Chloramphenicol + Clotrimazole",
        "bottle",
        "B345",
        "2026-12-31",
        20,
        120.00,
        12.0,
        "Combination ear drops for bacterial and fungal ear infections (otitis externa) — relieves pain, itching, and inflammation.",
        "Warm bottle in hand before use. Lie with affected ear up and instill drops. Keep warm for 5 minutes.",
    ),
    (
        "Paracetamol Syrup 60ml",
        "Paracetamol",
        "bottle",
        "B346",
        "2026-11-30",
        60,
        50.00,
        12.0,
        "Liquid antipyretic and analgesic for fever and pain relief in children and adults who cannot swallow tablets.",
        "Use provided measuring cup/dose syringe. Shake well before use. Do not exceed 4 doses in 24 hours.",
    ),
    (
        "Amoxicillin Dry Syrup 30ml",
        "Amoxicillin Trihydrate",
        "bottle",
        "B347",
        "2026-10-31",
        40,
        70.00,
        5.0,
        "Oral penicillin antibiotic suspension for bacterial infections in children and adults — respiratory, ear, and skin infections.",
        "Shake well before use. Measure dose accurately. Complete full course even if symptoms improve.",
    ),
    (
        "Cetirizine Syrup 60ml",
        "Cetirizine Hydrochloride",
        "bottle",
        "B348",
        "2026-12-31",
        40,
        60.00,
        12.0,
        "Antihistamine liquid for allergy relief — runny nose, sneezing, itchy eyes, and urticaria.",
        "Shake well before use. May cause mild drowsiness — avoid driving until response is known.",
    ),
    (
        "Ceftriaxone 1g Injection",
        "Ceftriaxone Sodium",
        "injection",
        "B349",
        "2027-06-30",
        100,
        50.00,
        5.0,
        "Third-generation cephalosporin injectable antibiotic for severe bacterial infections including meningitis, sepsis, and pneumonia.",
        "For intramuscular or intravenous use only. Administer by healthcare professional. Do not mix with calcium-containing solutions.",
    ),
    (
        "Diclofenac Injection 3ml",
        "Diclofenac Sodium",
        "injection",
        "B350",
        "2027-08-31",
        100,
        15.00,
        5.0,
        "Injectable NSAID for severe pain and inflammation — used postoperatively, for acute gout, and musculoskeletal disorders.",
        "For intramuscular or IV use by healthcare professional. Take with food if oral conversion needed.",
    ),
    (
        "Ondansetron Injection 2ml",
        "Ondansetron Hydrochloride",
        "injection",
        "B351",
        "2027-05-31",
        80,
        20.00,
        5.0,
        "Injectable anti-emetic for preventing nausea and vomiting associated with chemotherapy, radiation, and postoperative conditions.",
        "Administer by healthcare professional. Slow IV injection over 15-30 seconds.",
    ),
    (
        "Dexamethasone Injection 2ml",
        "Dexamethasone Sodium Phosphate",
        "injection",
        "B352",
        "2027-09-30",
        80,
        12.00,
        5.0,
        "Injectable corticosteroid for severe inflammation, allergic reactions, asthma exacerbation, and cerebral edema.",
        "For IM, IV, or topical use by healthcare professional. Not for prolonged use without medical supervision.",
    ),
    (
        "Vitamin E 400mg Capsule",
        "Tocopherol Acetate",
        "capsule",
        "B353",
        "2027-12-31",
        400,
        5.00,
        12.0,
        "Fat-soluble antioxidant for skin health, wound healing, immune function, and preventing vitamin E deficiency.",
        "Take with food. Fat-soluble — absorption enhanced with dietary fat. Do not exceed 400 IU/day without medical advice.",
    ),
    (
        "Mecobalamin 1500mcg Tablet",
        "Mecobalamin",
        "tablet",
        "B354",
        "2027-11-30",
        300,
        8.00,
        12.0,
        "Active form of vitamin B12 for peripheral neuropathy, diabetic neuropathy, and megaloblastic anemia.",
        "Take after meals. Supports nerve regeneration and red blood cell formation.",
    ),
    (
        "Prednisolone 10mg Tablet",
        "Prednisolone",
        "tablet",
        "B355",
        "2027-07-31",
        300,
        5.00,
        5.0,
        "Corticosteroid for inflammation, allergies, asthma, autoimmune disorders, and certain cancers.",
        "Take with food in the morning to match natural cortisol rhythm. Never stop abruptly — taper under medical supervision.",
    ),
    (
        "Dexamethasone 0.5mg Tablet",
        "Dexamethasone",
        "tablet",
        "B356",
        "2027-08-31",
        200,
        2.00,
        5.0,
        "Long-acting corticosteroid for inflammation, allergies, cerebral edema, and adrenal insufficiency.",
        "Take in the morning with food. Dose tapered gradually. Monitor blood sugar and blood pressure.",
    ),
    (
        "Allopurinol 100mg Tablet",
        "Allopurinol",
        "tablet",
        "B357",
        "2027-10-31",
        200,
        3.00,
        5.0,
        "Xanthine oxidase inhibitor for gout prevention and hyperuricemia — reduces uric acid production.",
        "Take after meals with plenty of water. Starting dose low and gradually increased. Avoid alcohol.",
    ),
    (
        "Febuxostat 40mg Tablet",
        "Febuxostat",
        "tablet",
        "B358",
        "2027-09-30",
        150,
        8.00,
        5.0,
        "Xanthine oxidase inhibitor for chronic hyperuricemia and gout — lowers serum uric acid levels.",
        "Take once daily with or without food. Increase fluid intake. Monitor liver function periodically.",
    ),
    (
        "Artemether + Lumefantrine (6)",
        "Artemether + Lumefantrine",
        "strip",
        "B359",
        "2027-04-30",
        50,
        150.00,
        5.0,
        "Combination antimalarial for treating uncomplicated Plasmodium falciparum malaria in endemic areas.",
        "Take with fat-containing food for absorption. Complete full 6-dose course as directed.",
    ),
    (
        "Hydrogen Peroxide 100ml",
        "Hydrogen Peroxide",
        "bottle",
        "B360",
        "2026-12-31",
        30,
        40.00,
        18.0,
        "Antiseptic and wound cleanser for cleaning cuts, abrasions, and minor burns — also used as mouth rinse.",
        "Dilute for mouth rinse (1 part peroxide to 2 parts water). For external wound cleaning only. Avoid contact with eyes.",
    ),
    (
        "Surgical Spirit 100ml",
        "Methylated Spirit",
        "bottle",
        "B361",
        "2028-02-29",
        30,
        50.00,
        18.0,
        "Topical antiseptic for cleaning skin, sterilizing instruments, and disinfecting minor wounds before dressing.",
        "For external use only. Highly flammable — keep away from fire and heat. Use in well-ventilated areas.",
    ),
    (
        "Antiseptic Cream 20g",
        "Cetrimide + Chlorhexidine",
        "tube",
        "B362",
        "2027-06-30",
        40,
        45.00,
        18.0,
        "Broad-spectrum topical antiseptic cream for infected wounds, cuts, and burns — prevents and treats bacterial skin infections.",
        "Clean affected area before application. Apply thinly and cover if needed. For external use only.",
    ),
]


def mig_008_catalog(engine):
    """Backfill the full medicine catalog (skips names already present)."""
    with Session(engine) as s:
        added = 0
        for name, comp, unit, batch, exp, qty, price, gst, _desc, _use in CATALOG:
            if s.query(Medicine).filter(Medicine.name == name).count() == 0:
                s.add(
                    Medicine(
                        name=name,
                        composition=comp,
                        unit=unit,
                        batch_no=batch,
                        expiry_date=exp,
                        quantity=qty,
                        price=price,
                        gst_percent=gst,
                    )
                )
                added += 1
        s.commit()
        return added


def mig_009_catalog_extra(engine):
    """Backfill the second catalog wave (skips names already present)."""
    with Session(engine) as s:
        for name, comp, unit, batch, exp, qty, price, gst, _desc, _use in CATALOG_EXTRA:
            if s.query(Medicine).filter(Medicine.name == name).count() == 0:
                s.add(
                    Medicine(
                        name=name,
                        composition=comp,
                        unit=unit,
                        batch_no=batch,
                        expiry_date=exp,
                        quantity=qty,
                        price=price,
                        gst_percent=gst,
                    )
                )
        s.commit()


def mig_010_medicine_details(engine):
    """Add description and usage columns to medicines and backfill all catalog entries."""
    _ensure_column(engine, "medicines", "description", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(engine, "medicines", "usage", "TEXT NOT NULL DEFAULT ''")
    with Session(engine) as s:
        all_data = CATALOG + CATALOG_EXTRA
        updated = 0
        for name, comp, unit, batch, exp, qty, price, gst, desc, use in all_data:
            s.execute(
                text(
                    "UPDATE medicines SET description = :d, usage = :u WHERE name = :n AND (description = '' OR usage = '')"
                ),
                {"d": desc, "u": use, "n": name},
            )
            updated += 1
        s.commit()
        return updated


def mig_011_bill_item_details(engine):
    """Add medicine_description and medicine_usage columns to bill_items."""
    _ensure_column(
        engine, "bill_items", "medicine_description", "TEXT NOT NULL DEFAULT ''"
    )
    _ensure_column(engine, "bill_items", "medicine_usage", "TEXT NOT NULL DEFAULT ''")


def mig_012_pharmacy_tables(engine):
    """Suppliers, customers ledger + stock movement audit trail."""
    Base.metadata.create_all(engine)
    # Backfill customers from historic bills (group by phone or name).
    with Session(engine) as s:
        if s.query(Customer).count() == 0:
            rows = s.execute(
                text(
                    "SELECT customer_name, customer_phone, COUNT(*), "
                    "COALESCE(SUM(grand_total),0), MAX(created_at) "
                    "FROM bills GROUP BY customer_name, customer_phone"
                )
            ).fetchall()
            for name, phone, cnt, spent, last in rows:
                if not (name or phone):
                    continue
                s.add(
                    Customer(
                        name=name or "",
                        phone=phone or "",
                        total_bills=int(cnt or 0),
                        total_spent=float(spent or 0),
                        last_visit=last or "",
                    )
                )
            s.commit()


def mig_013_medicine_pharmacy_fields(engine):
    """MRP, supplier, rack, schedule, Rx flag, per-item min stock."""
    _ensure_column(engine, "medicines", "mrp", "REAL NOT NULL DEFAULT 0.0")
    _ensure_column(engine, "medicines", "supplier", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(engine, "medicines", "rack", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(engine, "medicines", "schedule", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(
        engine, "medicines", "rx_required", "BOOLEAN NOT NULL DEFAULT 0"
    )
    _ensure_column(engine, "medicines", "min_stock", "INTEGER NOT NULL DEFAULT 0")
    # Sensible defaults: scheduled drugs commonly need prescription.
    with Session(engine) as s:
        try:
            s.execute(
                text(
                    "UPDATE medicines SET mrp = price WHERE mrp = 0 OR mrp IS NULL"
                )
            )
            s.commit()
        except Exception:
            s.rollback()


def mig_014_bill_pharmacy_fields(engine):
    """Bill status (completed/returned), doctor + prescription for compliance."""
    _ensure_column(
        engine, "bills", "status", "TEXT NOT NULL DEFAULT 'completed'"
    )
    _ensure_column(engine, "bills", "doctor_name", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(
        engine, "bills", "prescription_no", "TEXT NOT NULL DEFAULT ''"
    )


def migrate(engine, admin_user="admin", admin_pass="admin"):
    """Apply all pending migrations in order. Returns list of applied versions."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {SCHEMA_VERSIONS_TABLE} (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
        )
        applied = {
            r[0]
            for r in conn.execute(
                text(f"SELECT version FROM {SCHEMA_VERSIONS_TABLE}")
            ).fetchall()
        }

    migrations = [
        (1, "baseline tables", lambda: mig_001_baseline(engine)),
        (2, "legacy column backfill", lambda: mig_002_legacy_columns(engine)),
        (3, "seed admin", lambda: mig_003_seed_admin(engine, admin_user, admin_pass)),
        (4, "seed master data + stock", lambda: mig_004_seed_master_data(engine)),
        (5, "store profile", lambda: mig_005_store_profile(engine)),
        (6, "payment modes + stock limit", lambda: mig_006_payment_modes(engine)),
        (7, "medicine composition", lambda: mig_007_composition(engine)),
        (8, "full medicine catalog", lambda: mig_008_catalog(engine)),
        (9, "catalog wave two", lambda: mig_009_catalog_extra(engine)),
        (
            10,
            "medicine description and usage",
            lambda: mig_010_medicine_details(engine),
        ),
        (
            11,
            "bill item description and usage",
            lambda: mig_011_bill_item_details(engine),
        ),
        (12, "suppliers/customers/stock ledger", lambda: mig_012_pharmacy_tables(engine)),
        (
            13,
            "medicine pharmacy fields",
            lambda: mig_013_medicine_pharmacy_fields(engine),
        ),
        (14, "bill status/doctor fields", lambda: mig_014_bill_pharmacy_fields(engine)),
    ]
    done = []
    for version, _name, fn in migrations:
        if version not in applied:
            fn()
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT INTO {SCHEMA_VERSIONS_TABLE} (version, applied_at) VALUES (:v, :t)"
                    ),
                    {"v": version, "t": _now()},
                )
            done.append(version)
    return done
