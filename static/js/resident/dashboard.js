{# Ipinapahiwatig na gagamitin nito ang pangkalahatang layout(base.html) na naglalaman ng navigation bar at footer # }
{% extends "base.html" %}

{# Nilalagyan ng pamagat ang browser tab ng "Resident Dashboard" # }
{% block title %}Resident Dashboard{% endblock %}

{% block page_css %}
{# Pag - attach ng nakalaang CSS stylesheet para sa disenyo at hitsura ng resident dashboard # }
<link rel="stylesheet" href="{{ url_for('static', filename='css/resident/dashboard.css') }}">
    {% endblock %}

    {% block content %}
    <div class="container">

        {# Bahagi ng pagbati: Kinukuha ang unang pangalan ng nakarehistrong residente mula sa database #}
        <div class="dashboard-header">
            <h1>Welcome, {{ resident.first_name }}!</h1>
            <p class="dashboard-subtitle">Here is an overview of your document requests and account status.</p>
        </div>

        {# Mga mabilisang aksyon o pindutan para sa residente (Paggawa ng bagong request o pagtingin sa listahan) #}
        <div class="dashboard-actions">
            <a href="{{ url_for('new_request') }}" class="btn">Request a Document</a>
            <a href="{{ url_for('my_requests') }}" class="btn btn-outline">View All Requests</a>
        </div>

        {# Stat Grid: Nagpapakita ng bilang kung ilan ang request sa bawat status (Submitted, Approved, atbp.) #}
        <div class="stat-grid">
            <div class="stat-card">
                {# Kinukuha ang bilang ng 'Submitted' mula sa dictionary ng status_counts; kung wala, 0 ang ipapakita #}
                <span class="stat-number">{{ status_counts.get('Submitted', 0) }}</span>
                <span class="stat-label">Submitted</span>
            </div>
            <div class="stat-card">
                <span class="stat-number">{{ status_counts.get('Under Review', 0) }}</span>
                <span class="stat-label">Under Review</span>
            </div>
            <div class="stat-card">
                <span class="stat-number">{{ status_counts.get('Approved', 0) }}</span>
                <span class="stat-label">Approved</span>
            </div>
            <div class="stat-card">
                <span class="stat-number">{{ status_counts.get('Ready for Release', 0) }}</span>
                <span class="stat-label">Ready for Release</span>
            </div>
        </div>

        {# Seksyon para sa mga pinakahuling hiningi o isinumiteng dokumento ng residente #}
        <div class="card recent-requests-card">
            <h2>Recent Requests</h2>

            {# Sinusuri kung may laman ba ang listahan ng mga huling request #}
            {% if recent_requests %}
            <div class="table-wrapper">
                <table class="requests-table">
                    <thead>
                        <tr>
                            <th>Document Type</th>
                            <th>Purpose</th>
                            <th>Status</th>
                            <th>Date Requested</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {# Loop o pag-ikot sa bawat request na nasa recent_requests #}
                        {% for req in recent_requests %}
                        <tr>
                            {# Pangalan ng dokumento na hiniling #}
                            <td><strong>{{ req.document_name }}</strong></td>

                            {# Layunin kung bakit hiningi ang dokumento #}
                            <td>{{ req.purpose }}</td>

                            {# Status ng request na may kasamang badge para sa kulay #}
                            <td>
                                <span class="badge badge-{{ req.status|lower|replace(' ', '-') }}">
                                    {{ req.status }}
                                </span>
                            </td>

                            {# Petsa ng paggawa (kinukuha lang ang unang 10 na letra para sa eksaktong petsa YYYY-MM-DD) #}
                            <td>{{ req.created_at[:10] }}</td>

                            {# Pindutan para makita ang kumpletong detalye ng partikular na request #}
                            <td>
                                <a href="{{ url_for('request_details', request_id=req.id) }}" class="btn btn-small">View Details</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            {% else %}
            {# Lalabas lamang ang bahaging ito KUNG WALA PANG nare-request na dokumento ang residente #}
            <div class="empty-state">
                <p>You haven't requested any documents yet.</p>
                <a href="{{ url_for('new_request') }}" class="btn btn-small">Make your first request</a>
            </div>
            {% endif %}

        </div>
    </div>
    {% endblock %}