requireAuth();

document.addEventListener("DOMContentLoaded", async () => {
  renderAppShell({
    active: "leads",
    title: "Lead Pipeline",
    subtitle: "Google Maps, website parsing, LinkedIn discovery, and SMTP verification feed the verified lead queue here.",
    content: `
      <div class="grid cols-2">
        <div class="card">
          <h2>Add Lead</h2>
          <form class="form" id="lead-form">
            <div class="field"><label>Email</label><input name="email" type="email" /></div>
            <div class="field"><label>Phone</label><input name="phone" type="text" /></div>
            <div class="field"><label>First name</label><input name="first_name" type="text" /></div>
            <div class="field"><label>Last name</label><input name="last_name" type="text" /></div>
            <div class="field"><label>Company</label><input name="company" type="text" /></div>
            <div class="field"><label>Title</label><input name="title" type="text" /></div>
            <button class="btn btn-primary" type="submit">Save lead</button>
          </form>
        </div>
        <div class="card">
          <h2>Recent Leads</h2>
          <div id="leads-table"></div>
        </div>
      </div>
    `,
  });

  async function loadLeads() {
    const leads = await apiFetch("/leads/");
    document.getElementById("leads-table").innerHTML = leads.length
      ? `
        <table class="table">
          <thead><tr><th>Name</th><th>Company</th><th>Status</th></tr></thead>
          <tbody>
            ${leads
              .map(
                (lead) => `
                  <tr>
                    <td>${[lead.first_name, lead.last_name].filter(Boolean).join(" ") || lead.email || "Unknown"}</td>
                    <td>${lead.company || "-"}</td>
                    <td>${lead.status}</td>
                  </tr>
                `
              )
              .join("")}
          </tbody>
        </table>
      `
      : '<div class="empty">No leads yet.</div>';
  }

  document.getElementById("lead-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = Object.fromEntries(form.entries());
    await apiFetch("/leads/", { method: "POST", body: JSON.stringify(payload) });
    event.target.reset();
    loadLeads();
  });

  loadLeads();
});
