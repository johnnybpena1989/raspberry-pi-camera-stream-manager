document.addEventListener('DOMContentLoaded', function() {
    // Function to update stream status indicators
    function updateStreamStatus(streamId, status, error) {
        const statusElement = document.querySelector(`#stream-status-${streamId}`);
        const streamContainer = document.querySelector(`#stream-container-${streamId}`);

        if (status) {
            statusElement.className = 'badge bg-success';
            statusElement.textContent = 'Online';
            streamContainer.classList.remove('stream-offline');
        } else {
            statusElement.className = 'badge bg-danger';
            statusElement.textContent = 'Offline';
            streamContainer.classList.add('stream-offline');
            streamContainer.setAttribute('data-error', `Stream Offline: ${error || 'Connection failed'}`);
        }
    }

    // Function to check all stream statuses
    function checkStreamStatuses() {
        fetch('/check_streams')
            .then(response => response.json())
            .then(streams => {
                streams.forEach(stream => {
                    updateStreamStatus(stream.id, stream.status, stream.error);
                });
            })
            .catch(error => {
                console.error('Error checking stream statuses:', error);
            });
    }

    // Check stream statuses periodically (every 30 seconds instead of 10)
    setInterval(checkStreamStatuses, 30000);

    // Initial status check
    checkStreamStatuses();
});