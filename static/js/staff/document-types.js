/* =============================================================================
   DOCUMENT TYPES JAVASCRIPT (static/js/staff/document_types.js)
   ============================================================================= */

function openAddModal() {
    const modal = document.getElementById('doc-type-modal');
    const form = document.getElementById('doc-type-form');
    const title = document.getElementById('modal-title');

    if (!modal || !form || !title) return;

    title.textContent = 'Add Document Type';
    document.getElementById('doc_id').value = '';
    form.reset();

    const feeInput = document.getElementById('fee');
    if (feeInput) feeInput.value = '0.00';

    modal.hidden = false;
}

function openEditModal(doc) {
    const modal = document.getElementById('doc-type-modal');
    const title = document.getElementById('modal-title');

    if (!modal || !title) return;

    title.textContent = 'Edit Document Type';
    document.getElementById('doc_id').value = doc.id;
    document.getElementById('name').value = doc.name || '';
    document.getElementById('description').value = doc.description || '';
    document.getElementById('fee').value = doc.fee || 0;
    document.getElementById('processing_days').value = doc.processing_days || 1;
    document.getElementById('requirements').value = doc.requirements || '';

    modal.hidden = false;
}

function closeModal() {
    const modal = document.getElementById('doc-type-modal');
    if (modal) {
        modal.hidden = true;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('doc-type-modal');
    if (modal) {
        modal.addEventListener('click', (event) => {
            if (event.target === modal) {
                closeModal();
            }
        });
    }

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeModal();
        }
    });

    // Event listener para sa mga Edit buttons gamit ang data-doc attribute
    document.querySelectorAll('.btn-edit').forEach(button => {
        button.addEventListener('click', () => {
            try {
                const docAttr = button.getAttribute('data-doc');
                const doc = JSON.parse(docAttr);
                openEditModal(doc);
            } catch (e) {
                console.error('Error parsing document JSON:', e);
            }
        });
    });
});