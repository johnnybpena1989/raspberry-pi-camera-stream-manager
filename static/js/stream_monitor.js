document.addEventListener('DOMContentLoaded', function() {
    // Function to update stream status indicators
    function updateStreamStatus(streamId, status) {
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
        }
    }

    // Function to check all stream statuses
    function checkStreamStatuses() {
        fetch('/check_streams')
            .then(response => response.json())
            .then(streams => {
                streams.forEach(stream => {
                    updateStreamStatus(stream.id, stream.status);
                });
            })
            .catch(error => {
                console.error('Error checking stream statuses:', error);
            });
    }

    // Check stream statuses periodically
    setInterval(checkStreamStatuses, 10000);

    // Initial status check
    checkStreamStatuses();
});
