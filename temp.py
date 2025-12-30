from collections import defaultdict
import random


supervisors = ["A", "B", "C", "D"]

sessions = [
    ("Day1", "M"), ("Day1", "E"),
    ("Day2", "M"), ("Day2", "E"),
    ("Day3", "M"), ("Day3", "E"),
    ("Day4", "M"), ("Day4", "E"),
]

availability = {
    ("Day1", "M"): ["A", "B", "C", "D"],
    ("Day1", "E"): ["A", "B", "C", "D"],
    ("Day2", "M"): ["A", "B"],
    ("Day2", "E"): ["A", "B"],
    ("Day3", "M"): ["A", "B"],
    ("Day3", "E"): ["A", "B"],
    ("Day4", "M"): ["A", "B"],
    ("Day4", "E"): ["A", "B"],
}


roles = []
for s in sessions:
    roles.append((s, "MAIN"))
    roles.append((s, "BACKUP"))


total_roles = len(roles)
n = len(supervisors)

ideal = total_roles // n
max_fair = ideal + 1

availability_count = defaultdict(int)
for s in sessions:
    for sup in availability[s]:
        availability_count[sup] += 2

max_allowed = {
    sup: min(max_fair, availability_count[sup])
    for sup in supervisors
}


def role_choices(role):
    session, _ = role
    return len(availability[session])

roles.sort(key=lambda r: (role_choices(r), 0 if r[1] == "MAIN" else 1))



duty_count = defaultdict(int)
assignments = {}
fairness_violated = False

for role in roles:
    session, role_type = role
    used = set()

    if role_type == "BACKUP":
        used.add(assignments[(session, "MAIN")])

    
    eligible = [
        sup for sup in availability[session]
        if sup not in used and duty_count[sup] < max_allowed[sup]
    ]

   
    if not eligible:
        fairness_violated = True
        eligible = [
            sup for sup in availability[session]
            if sup not in used
        ]

    if not eligible:
        raise Exception("No supervisor available at all for " + str(role))

    
    min_load = min(duty_count[s] for s in eligible)
    candidates = [s for s in eligible if duty_count[s] == min_load]
    chosen = random.choice(candidates)

    assignments[role] = chosen
    duty_count[chosen] += 1


print("\nSCHEDULE:\n")
for session in sessions:
    print(session,
          "MAIN:", assignments[(session, "MAIN")],
          "BACKUP:", assignments[(session, "BACKUP")])

print("\nDUTY COUNT:")
for sup in supervisors:
    print(sup, ":", duty_count[sup])

diff = max(duty_count.values()) - min(duty_count.values())
print("\nMax - Min Difference:", diff)

if fairness_violated:
    print("\n⚠️ Fairness constraint was relaxed due to availability/backup constraints.")
else:
    print("\n✅ Strict fairness maintained.")
