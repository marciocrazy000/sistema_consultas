document.addEventListener('DOMContentLoaded', function() {
    // Função para gerenciar o desaparecimento dos alertas flutuantes
    function manageFloatingAlerts() {
        var alerts = document.querySelectorAll('.alert-float');

        alerts.forEach(function(alert) {
            var displayTime = 1500; // Tempo em milissegundos para ficar visível (1.5s)
            var animationTime = 500; // Tempo em milissegundos da animação de saída (0.5s no CSS)

            // 1. Faz o alerta aparecer suavemente (animação de entrada)
            setTimeout(function() {
                alert.classList.add('show');
            }, 100);

            // 2. Inicia o temporizador para começar a sumir
            setTimeout(function() {
                // Remove a classe 'show' para iniciar a animação de saída
                alert.classList.remove('show');

                // 3. Remove o elemento do DOM após a animação de saída terminar
                setTimeout(function() {
                    alert.remove();
                }, animationTime);

            }, displayTime);
        });
    }

    // Chama a função quando o conteúdo da página estiver carregado
    manageFloatingAlerts();
});