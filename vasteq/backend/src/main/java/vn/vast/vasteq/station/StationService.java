package vn.vast.vasteq.station;

import java.util.*;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import jakarta.persistence.PersistenceException;
import jakarta.transaction.Transactional;
import jakarta.validation.Validator;
import org.eclipse.microprofile.jwt.JsonWebToken;
import org.hibernate.exception.ConstraintViolationException;
import vn.vast.vasteq.user.AccountAccess;
import vn.vast.vasteq.user.ApiException;

@ApplicationScoped
@Transactional
public class StationService {
    private static final Set<String> FIELDS = Set.of("networkCode", "stationCode", "name", "city",
        "province", "instrumentType", "instrumentSerial", "coordinateCrs", "latitude", "longitude",
        "elevationM", "metadataUri", "metadataSource");
    @Inject StationRepository repository;
    @Inject AccountAccess access;
    @Inject ObjectMapper mapper;
    @Inject Validator validator;

    public record Page(List<Station> items, long total, int offset, int limit) {}

    public Page list(JsonWebToken jwt, StationFilters filters) {
        access.require(jwt, false);
        if ((long) filters.offset + filters.limit - 1 > Integer.MAX_VALUE)
            throw new ApiException(400, "invalid_pagination", "Offset plus limit exceeds the supported range");
        List<String> clauses = new ArrayList<>();
        Map<String, Object> params = new HashMap<>();
        filter(clauses, params, "networkCode", filters.networkCode);
        filter(clauses, params, "stationCode", filters.stationCode);
        filter(clauses, params, "province", filters.province);
        filter(clauses, params, "city", filters.city);
        if (filters.hasCoordinates != null)
            clauses.add("true".equals(filters.hasCoordinates) ? "latitude is not null and longitude is not null"
                : "latitude is null and longitude is null");
        if (filters.search != null && !filters.search.isBlank()) {
            clauses.add("lower(name) like :search escape '!'");
            String term = filters.search.strip().toLowerCase(Locale.ROOT)
                .replace("!", "!!").replace("%", "!%").replace("_", "!_");
            params.put("search", "%" + term + "%");
        }
        String where = String.join(" and ", clauses);
        String query = where.isEmpty() ? "order by id" : where + " order by id";
        long total = where.isEmpty() ? repository.count() : repository.count(where, params);
        List<Station> items = repository.find(query, params)
            .range(filters.offset, filters.offset + filters.limit - 1).list();
        return new Page(items, total, filters.offset, filters.limit);
    }

    private void filter(List<String> clauses, Map<String, Object> params, String field, String value) {
        if (value != null && !value.isBlank()) {
            clauses.add(field + " = :" + field);
            params.put(field, value.strip());
        }
    }

    public Station get(JsonWebToken jwt, long id) {
        access.require(jwt, false);
        return required(id);
    }

    public Station create(JsonWebToken jwt, StationInput input) {
        access.require(jwt, true);
        validate(input);
        Station station = new Station();
        station.apply(input);
        availableCodes(station);
        try {
            repository.persist(station);
            repository.flush();
        } catch (PersistenceException e) {
            throw translate(e);
        }
        return station;
    }

    public Station update(JsonWebToken jwt, long id, JsonNode patch) {
        access.require(jwt, true);
        Station station = required(id);
        if (!patch.isObject() || patch.isEmpty())
            throw new ApiException(400, "invalid_update", "Provide a nonempty JSON object");
        ObjectNode merged = mapper.valueToTree(station.input());
        Iterator<String> fields = patch.fieldNames();
        while (fields.hasNext()) {
            String field = fields.next();
            if (!FIELDS.contains(field))
                throw new ApiException(400, "unknown_field", "Unknown station field: " + field);
            merged.set(field, patch.get(field));
        }
        StationInput input;
        try {
            input = mapper.treeToValue(merged, StationInput.class);
        } catch (JsonProcessingException | IllegalArgumentException e) {
            throw new ApiException(400, "invalid_update", "Invalid station field value");
        }
        validate(input);
        station.apply(input);
        availableCodes(station);
        try {
            repository.flush();
        } catch (PersistenceException e) {
            throw translate(e);
        }
        return station;
    }

    public void delete(JsonWebToken jwt, long id) {
        access.require(jwt, true);
        Station station = required(id);
        try {
            repository.delete(station);
            // The database FK also protects against channels added concurrently.
            repository.flush();
        } catch (PersistenceException e) {
            throw translate(e);
        }
    }

    private Station required(long id) {
        Station station = repository.findById(id);
        if (station == null) throw new ApiException(404, "station_not_found", "Station not found");
        return station;
    }

    private void validate(StationInput input) {
        if (!validator.validate(input).isEmpty())
            throw new ApiException(400, "invalid_station", "Invalid station field value or length");
        if ((input.latitude() == null) != (input.longitude() == null))
            throw new ApiException(400, "coordinate_pair_required", "Latitude and longitude must be supplied or cleared together");
    }

    private void availableCodes(Station station) {
        // Avoid auto-flushing a modified entity before reporting a duplicate.
        Long existingId = repository.getEntityManager()
            .createQuery("select id from Station where networkCode = :network and stationCode = :station", Long.class)
            .setParameter("network", station.networkCode).setParameter("station", station.stationCode)
            .setFlushMode(jakarta.persistence.FlushModeType.COMMIT)
            .getResultStream().findFirst().orElse(null);
        if (existingId != null && !existingId.equals(station.id))
            throw new ApiException(409, "station_exists", "A station with these network and station codes already exists");
    }

    private RuntimeException translate(PersistenceException error) {
        for (Throwable cause = error; cause != null; cause = cause.getCause()) {
            if (cause instanceof ConstraintViolationException violation) {
                if (violation.getErrorCode() == 1062 || "23505".equals(violation.getSQLState()))
                    return new ApiException(409, "station_exists", "A station with these network and station codes already exists");
                if (violation.getErrorCode() == 1451 || "23503".equals(violation.getSQLState()))
                    return new ApiException(409, "station_in_use", "Station cannot be deleted while channels reference it");
            }
        }
        return error;
    }
}
