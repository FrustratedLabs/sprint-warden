package example;

/** The sprintwarden Gradle example: temperature conversions. */
public final class Temperature {
    private Temperature() {}

    /** Sprint S01. */
    public static double celsiusToFahrenheit(double c) {
        return c * 9 / 5 + 32;
    }

    /** Sprint S01. */
    public static double fahrenheitToCelsius(double f) {
        return (f - 32) * 5 / 9;
    }

    /** Sprint S02. */
    public static double celsiusToKelvin(double c) {
        if (c < -273.15) {
            throw new IllegalArgumentException("below absolute zero");
        }
        return c + 273.15;
    }
}
