package vn.vast.vasteq.station;

import java.math.BigDecimal;
import jakarta.validation.constraints.*;

public record StationInput(
    @NotBlank @Size(max=2) @Pattern(regexp="[\\x21-\\x7E]+") String networkCode,
    @NotBlank @Size(max=5) @Pattern(regexp="[\\x21-\\x7E]+") String stationCode,
    @Size(max=120) String name,
    @Size(max=120) String city,
    @Size(max=120) String province,
    @Size(max=64) String instrumentType,
    @Size(max=64) String instrumentSerial,
    @Size(max=64) String coordinateCrs,
    @DecimalMin("-90") @DecimalMax("90") @Digits(integer=3, fraction=6) BigDecimal latitude,
    @DecimalMin("-180") @DecimalMax("180") @Digits(integer=4, fraction=6) BigDecimal longitude,
    @Digits(integer=7, fraction=3) BigDecimal elevationM,
    @Size(max=1024) String metadataUri,
    @Size(max=255) String metadataSource
) {
    public StationInput {
        networkCode = trim(networkCode); stationCode = trim(stationCode);
        name = trim(name); city = trim(city); province = trim(province);
        instrumentType = trim(instrumentType); instrumentSerial = trim(instrumentSerial);
        coordinateCrs = trim(coordinateCrs); metadataUri = trim(metadataUri);
        metadataSource = trim(metadataSource);
    }
    private static String trim(String value) { return value == null ? null : value.strip(); }
}
