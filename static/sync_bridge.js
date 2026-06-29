const SyncBridge = {
    QUEUE_KEY: 'learn2master_sync_queue',

    addToQueue: function(assessmentData) {
        let queue = JSON.parse(localStorage.getItem(this.QUEUE_KEY) || '[]');
        assessmentData.timestamp = new Date().toISOString();
        queue.push(assessmentData);
        localStorage.setItem(this.QUEUE_KEY, JSON.stringify(queue));
        this.trySync();
    },

    trySync: async function() {
        if (!navigator.onLine) return;

        let queue = JSON.parse(localStorage.getItem(this.QUEUE_KEY) || '[]');
        if (queue.length === 0) return;

        try {
            const response = await fetch('/sync/assessments', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ attempts: queue })
            });

            if (response.ok) {
                localStorage.setItem(this.QUEUE_KEY, '[]');
                console.log('Synchronization successful.');
                window.location.reload(); // Refresh to update UI with synced data
            }
        } catch (error) {
            console.error('Synchronization failed:', error);
        }
    },

    getCSRFToken: function() {
        return document.querySelector('input[name="csrf_token"]')?.value || '';
    }
};

window.addEventListener('online', () => SyncBridge.trySync());
