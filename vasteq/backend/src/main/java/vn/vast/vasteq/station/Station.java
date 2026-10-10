package vn.vast.vasteq.station;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import jakarta.persistence.*;

@Entity
@Table(name="stations", uniqueConstraints=@UniqueConstraint(name="uq_stations_codes", columnNames={"network_code", "station_code"}))
public class Station {
    @Id @GeneratedValue(strategy=GenerationType.IDENTITY)
    @Column(columnDefinition="BIGINT UNSIGNED") public Long id;
    @Column(name="network_code", nullable=false, length=2) public String networkCode;
    @Column(name="station_code", nullable=false, length=5) public String stationCode;
    @Column(length=120) public String name;
    @Column(length=120) public String city;
    @Column(length=120) public String province;
    @Column(name="instrument_type", length=64) public String instrumentType;
    @Column(name="instrument_serial", length=64) public String instrumentSerial;
    @Column(name="coordinate_crs", length=64) public String coordinateCrs;
    @Column(precision=9, scale=6) public BigDecimal latitude;
    @Column(precision=10, scale=6) public BigDecimal longitude;
    @Column(name="elevation_m", precision=10, scale=3) public BigDecimal elevationM;
    @Column(name="metadata_uri", length=1024) public String metadataUri;
    @Column(name="metadata_source", length=255) public String metadataSource;
    @Column(name="created_at", nullable=false, updatable=false) public LocalDateTime createdAt;
    @Column(name="updated_at", nullable=false) public LocalDateTime updatedAt;

    @PrePersist void created() { createdAt = LocalDateTime.now(ZoneOffset.UTC); updatedAt = createdAt; }
    @PreUpdate void updated() { updatedAt = LocalDateTime.now(ZoneOffset.UTC); }

    public StationInput input() {
        return new StationInput(networkCode, stationCode, name, city, province, instrumentType,
            instrumentSerial, coordinateCrs, latitude, longitude, elevationM, metadataUri, metadataSource);
    }
    public void apply(StationInput input) {
        networkCode = input.networkCode(); stationCode = input.stationCode();
        name = input.name(); city = input.city(); province = input.province();
        instrumentType = input.instrumentType(); instrumentSerial = input.instrumentSerial();
        coordinateCrs = input.coordinateCrs(); latitude = input.latitude(); longitude = input.longitude();
        elevationM = input.elevationM(); metadataUri = input.metadataUri(); metadataSource = input.metadataSource();
    }
}
