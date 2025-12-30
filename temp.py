export function generateSchedule({ supervisors, blocks, examData }) {

  
  const sessions = [];

  for (const day of examData.days) {
    for (const session of Object.keys(day.sessions)) {
      sessions.push({
        date: day.date,
        session,
        unavailable: day.unavailable,
        students: day.sessions[session]
      });
    }
  }

  
  const roles = [];
  for (const s of sessions) {
    roles.push({ session: s, role: "MAIN" });
    roles.push({ session: s, role: "BACKUP" });
  }

  
  const availability = new Map();

  for (const s of sessions) {
    const key = `${s.date}-${s.session}`;
    availability.set(
      key,
      supervisors.filter(sup => !s.unavailable.includes(sup))
    );
  }

  
  const totalRoles = roles.length;
  const n = supervisors.length;
  const ideal = Math.floor(totalRoles / n);
  const maxFair = ideal + 1;

  const availabilityCount = {};
  supervisors.forEach(s => availabilityCount[s] = 0);

  for (const list of availability.values()) {
    for (const s of list) availabilityCount[s] += 2;
  }

  const maxAllowed = {};
  supervisors.forEach(s => {
    maxAllowed[s] = Math.min(maxFair, availabilityCount[s]);
  });

  
  roles.sort((a, b) => {
    const aKey = `${a.session.date}-${a.session.session}`;
    const bKey = `${b.session.date}-${b.session.session}`;

    const diff =
      availability.get(aKey).length -
      availability.get(bKey).length;

    if (diff !== 0) return diff;

    if (a.role === "MAIN" && b.role === "BACKUP") return -1;
    if (a.role === "BACKUP" && b.role === "MAIN") return 1;
    return 0;
  });

  
  const dutyCount = {};
  const assignments = {};
  supervisors.forEach(s => dutyCount[s] = 0);

  let fairnessRelaxed = false;

  for (const r of roles) {
    const key = `${r.session.date}-${r.session.session}`;

    const used = new Set();
    if (r.role === "BACKUP") {
      used.add(assignments[`${key}-MAIN`]);
    }

    let eligible = availability
      .get(key)
      .filter(s => !used.has(s) && dutyCount[s] < maxAllowed[s]);

    if (eligible.length === 0) {
      fairnessRelaxed = true;
      eligible = availability.get(key).filter(s => !used.has(s));
    }

    const minLoad = Math.min(...eligible.map(s => dutyCount[s]));
    const candidates = eligible.filter(s => dutyCount[s] === minLoad);

    const chosen = candidates[Math.floor(Math.random() * candidates.length)];

    assignments[`${key}-${r.role}`] = chosen;
    dutyCount[chosen]++;
  }

  
  const scheduleBySupervisor = {};
  supervisors.forEach(s => scheduleBySupervisor[s] = []);


  const sortedBlocks = [...blocks].sort((a, b) => b.capacity - a.capacity);

  for (const s of sessions) {
    let remaining = s.students;
    const blocksUsed = [];

    for (const b of sortedBlocks) {
      if (remaining <= 0) break;
      blocksUsed.push(b.block);
      remaining -= b.capacity;
    }

    const main = assignments[`${s.date}-${s.session}-MAIN`];
    const backup = assignments[`${s.date}-${s.session}-BACKUP`];

    for (const block of blocksUsed) {
      scheduleBySupervisor[main].push({
        date: s.date,
        session: s.session,
        block,
        role: "MAIN"
      });

      scheduleBySupervisor[backup].push({
        date: s.date,
        session: s.session,
        block,
        role: "BACKUP"
      });
    }
  }

  return {
    scheduleBySupervisor,
    dutyReport: dutyCount,
    fairnessRelaxed
  };
}
