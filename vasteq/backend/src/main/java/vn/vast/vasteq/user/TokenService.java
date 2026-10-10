package vn.vast.vasteq.user;

import java.util.Set;
import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import io.smallrye.jwt.build.Jwt;

@ApplicationScoped
public class TokenService {
    @ConfigProperty(name="mp.jwt.verify.issuer") String issuer;
    @ConfigProperty(name="vasteq.jwt.ttl-seconds") long ttl;
    public UserDtos.Token issue(User user) {
        String token=Jwt.issuer(issuer).subject(Long.toString(user.id)).audience("vasteq-api")
            .groups(Set.of(user.role.name())).expiresIn(ttl).sign();
        return new UserDtos.Token(token,"Bearer",ttl,user.view());
    }
}
