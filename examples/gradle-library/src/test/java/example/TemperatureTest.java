package example;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class TemperatureTest {
    @Test
    void S01_celsiusToFahrenheit() {
        assertEquals(212.0, Temperature.celsiusToFahrenheit(100), 1e-9);
    }

    @Test
    void S01_fahrenheitToCelsius() {
        assertEquals(37.0, Temperature.fahrenheitToCelsius(98.6), 1e-9);
    }

    @Test
    @DisplayName("[S02] converts Celsius to Kelvin")
    void kelvin() {
        assertEquals(273.15, Temperature.celsiusToKelvin(0), 1e-9);
    }

    @Test
    @DisplayName("[S02] rejects temperatures below absolute zero")
    void belowAbsoluteZero() {
        assertThrows(IllegalArgumentException.class, () -> Temperature.celsiusToKelvin(-300));
    }

    @Test
    void roundTrip() {
        assertEquals(20.0, Temperature.fahrenheitToCelsius(Temperature.celsiusToFahrenheit(20)), 1e-9);
    }
}
